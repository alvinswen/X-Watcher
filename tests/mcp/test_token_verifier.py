"""token_verifier 认证路由测试:合法 key 放行 / 失效 key 拒绝(双向)。"""
import hashlib

import pytest
from mcp.server.auth.provider import AccessToken


@pytest.mark.asyncio
async def test_verify_token_file_mode_valid_and_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    from src.config import clear_settings_cache

    clear_settings_cache()

    from src.user.infrastructure.file_user_repository import FileUserStore

    store = FileUserStore(tmp_path)
    user = await store.create_user("Alice", "alice@example.com", "h")
    token = "valid-token-123"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    await store.create_api_key(user.id, key_hash, key_prefix="valid-to")

    from src.mcp.token_verifier import XWatcherTokenVerifier

    verifier = XWatcherTokenVerifier()
    # 合法 key 放行(路径可证:key 只在文件层;file 路由坏→DB 空→返 None→翻红)
    ok = await verifier.verify_token(token)
    assert isinstance(ok, AccessToken)
    assert ok.client_id == "Alice"
    assert ok.scopes == ["user"]
    # 失效 key 拒绝
    assert await verifier.verify_token("wrong-token") is None


@pytest.mark.asyncio
async def test_verify_token_file_mode_admin_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    from src.config import clear_settings_cache

    clear_settings_cache()

    from src.user.infrastructure.file_user_repository import FileUserStore

    store = FileUserStore(tmp_path)
    user = await store.create_user("Boss", "boss@example.com", "h")
    await store.update_user(user.id, is_admin=True)
    token = "admin-token"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    await store.create_api_key(user.id, key_hash, key_prefix="admin-to")

    from src.mcp.token_verifier import XWatcherTokenVerifier

    ok = await XWatcherTokenVerifier().verify_token(token)
    assert ok.scopes == ["admin", "user"]
    assert ok.client_id == "Boss"


@pytest.mark.asyncio
async def test_verify_token_sqlalchemy_mode(monkeypatch):
    """默认 sqlalchemy 模式两步走 provider 等价(patch session_maker 到内存库)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    from src.config import clear_settings_cache

    clear_settings_cache()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.database.models import ApiKey, Base, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    token = "sql-token"
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    async with maker() as s:
        u = User(name="Bob", email="bob@x.com", is_admin=False)
        s.add(u)
        await s.flush()
        s.add(ApiKey(user_id=u.id, key_hash=key_hash, key_prefix="sql-to", name="t", is_active=True))
        await s.commit()
    monkeypatch.setattr(
        "src.database.async_session.get_async_session_maker", lambda: maker
    )

    from src.mcp.token_verifier import XWatcherTokenVerifier

    ok = await XWatcherTokenVerifier().verify_token(token)
    assert ok is not None and ok.client_id == "Bob" and ok.scopes == ["user"]
    assert await XWatcherTokenVerifier().verify_token("nope") is None
    await engine.dispose()
