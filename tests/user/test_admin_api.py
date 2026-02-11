"""管理员用户操作 API (AdminUserRouter) 测试。"""

import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, status
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import clear_settings_cache
from src.database.models import Base, User as UserOrm
from src.main import app
from src.user.domain.models import UserDomain
from src.user.services.auth_service import AuthService


JWT_SECRET = "test-admin-api-jwt-secret-32bytes!!"


@pytest.fixture(autouse=True)
def setup_env():
    """设置测试环境变量。"""
    original_jwt = os.environ.get("JWT_SECRET_KEY")
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    clear_settings_cache()
    yield
    if original_jwt is None:
        os.environ.pop("JWT_SECRET_KEY", None)
    else:
        os.environ["JWT_SECRET_KEY"] = original_jwt
    clear_settings_cache()


@pytest.fixture
async def test_session():
    """独立的异步内存数据库会话。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


def _make_admin_user(user_id: int = 1) -> UserDomain:
    """构造管理员 UserDomain 对象。"""
    return UserDomain(
        id=user_id,
        name="admin",
        email="admin@test.com",
        is_admin=True,
        created_at=datetime.now(timezone.utc),
    )


def _make_normal_user(user_id: int = 2) -> UserDomain:
    """构造普通用户 UserDomain 对象。"""
    return UserDomain(
        id=user_id,
        name="normaluser",
        email="normal@test.com",
        is_admin=False,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
async def admin_client(test_session):
    """提供管理员认证的 async_client，覆盖 get_async_session 和 get_current_admin_user。"""
    from src.database.async_session import get_async_session
    from src.user.api.auth import get_current_admin_user

    admin_user = _make_admin_user()

    async def override_get_async_session():
        yield test_session

    async def override_get_current_admin_user():
        return admin_user

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, test_session

    app.dependency_overrides.pop(get_async_session, None)
    app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.fixture
async def non_admin_client(test_session):
    """提供非管理员认证的 async_client（覆盖 get_current_admin_user 抛出 403）。"""
    from src.database.async_session import get_async_session
    from src.user.api.auth import get_current_admin_user

    async def override_get_async_session():
        yield test_session

    async def override_get_current_admin_user():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_async_session, None)
    app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.mark.asyncio
async def test_create_user(admin_client):
    """POST /api/admin/users 创建用户返回 201 + user + temp_password + api_key。"""
    client, _ = admin_client

    resp = await client.post(
        "/api/admin/users",
        json={"name": "newuser", "email": "new@example.com"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["name"] == "newuser"
    assert data["user"]["email"] == "new@example.com"
    assert data["user"]["is_admin"] is False
    assert len(data["temp_password"]) == 12
    assert data["api_key"].startswith("sna_")


@pytest.mark.asyncio
async def test_create_user_duplicate_email(admin_client):
    """邮箱重复返回 409。"""
    client, _ = admin_client

    # 先创建一个用户
    resp1 = await client.post(
        "/api/admin/users",
        json={"name": "user1", "email": "dup@example.com"},
    )
    assert resp1.status_code == 201

    # 再用同样的邮箱创建
    resp2 = await client.post(
        "/api/admin/users",
        json={"name": "user2", "email": "dup@example.com"},
    )
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_user_non_admin(non_admin_client):
    """非管理员用户创建用户返回 403。"""
    client = non_admin_client

    resp = await client.post(
        "/api/admin/users",
        json={"name": "newuser", "email": "new@example.com"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_users(admin_client):
    """GET /api/admin/users 返回用户列表。"""
    client, _ = admin_client

    # 先创建两个用户
    await client.post("/api/admin/users", json={"name": "alice", "email": "alice@example.com"})
    await client.post("/api/admin/users", json={"name": "bob", "email": "bob@example.com"})

    resp = await client.get("/api/admin/users")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    emails = {u["email"] for u in data}
    assert "alice@example.com" in emails
    assert "bob@example.com" in emails


@pytest.mark.asyncio
async def test_reset_password(admin_client):
    """POST /api/admin/users/{id}/reset-password 返回新临时密码。"""
    client, _ = admin_client

    # 先创建用户
    create_resp = await client.post(
        "/api/admin/users",
        json={"name": "resetme", "email": "reset@example.com"},
    )
    assert create_resp.status_code == 201
    user_id = create_resp.json()["user"]["id"]
    old_temp = create_resp.json()["temp_password"]

    # 重置密码
    resp = await client.post(f"/api/admin/users/{user_id}/reset-password")

    assert resp.status_code == 200
    data = resp.json()
    assert "temp_password" in data
    assert len(data["temp_password"]) == 12
    assert data["temp_password"].isalnum()
    # 新临时密码应该和旧的不同（极小概率相同，但12字符字母数字基本不会）
    assert data["temp_password"] != old_temp


@pytest.mark.asyncio
async def test_admin_api_key_bootstrap(test_session, monkeypatch):
    """ADMIN_API_KEY 环境变量可执行管理操作。"""
    from src.database.async_session import get_async_session

    monkeypatch.setenv("ADMIN_API_KEY", "test-bootstrap-key")
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)
    clear_settings_cache()

    async def override_get_async_session():
        yield test_session

    app.dependency_overrides[get_async_session] = override_get_async_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/admin/users",
            json={"name": "bootstrap_user", "email": "bootstrap@example.com"},
            headers={"X-API-Key": "test-bootstrap-key"},
        )

    app.dependency_overrides.pop(get_async_session, None)

    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["name"] == "bootstrap_user"
    assert data["api_key"].startswith("sna_")
