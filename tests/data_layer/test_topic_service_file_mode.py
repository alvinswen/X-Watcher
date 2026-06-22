"""topic_service 在 XWATCHER_DATA_LAYER=file 下走文件层(topic 自有数据)。
跨域校验 _validate_username_in_scraper_follows 现走 get_follows_repo(file 模式=
FileFollowStore),故关注列表种子预置进文件层而非 DB session。"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database.models import Base, ScraperFollow
from src.topic.services.topic_service import TopicService


@pytest_asyncio.fixture
async def session(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    s = async_sessionmaker(engine, expire_on_commit=False)()
    # 跨域校验现走文件层(get_follows_repo file 模式=FileFollowStore)→ 种子进文件层
    from src.preference.infrastructure.file_follow_repository import FileFollowStore
    await FileFollowStore(tmp_path).create_scraper_follow("alice", "test", "test")
    yield s
    await s.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_topic_crud_and_accounts_file_mode(session, tmp_path):
    svc = TopicService()
    t = await svc.create_topic(session, name="AI", description="d")
    assert t.id is not None
    # 路由可证:create 后文件层盘面真被写,证 topic 自有数据走文件层(非 DB);
    # 若 provider file 路由坏掉(误返 sqlalchemy adapter),此断言翻红、不再假绿
    assert (tmp_path / "topics" / "topics.json").exists()
    listed = await svc.list_topics(session)
    assert any(x.id == t.id and x.account_count == 0 for x in listed)
    updated = await svc.update_topic(session, t.id, name="ML")
    assert updated.name == "ML"
    acct = await svc.add_account(session, t.id, "alice")          # 走 file(account)+ session(校验)
    assert acct.username == "alice"
    detail = await svc.get_topic(session, t.id)
    assert [a.username for a in detail.accounts] == ["alice"]
    set_res = await svc.set_accounts(session, t.id, ["alice"])
    assert [a.username for a in set_res] == ["alice"]
    assert await svc.remove_account(session, t.id, "alice") is True
    assert await svc.delete_topic(session, t.id) is True
    assert await svc.get_topic(session, t.id) is None


@pytest.mark.asyncio
async def test_add_account_rejects_unknown_username_file_mode(session):
    svc = TopicService()
    t = await svc.create_topic(session, name="AI")
    with pytest.raises(ValueError, match="未在系统抓取列表中注册"):
        await svc.add_account(session, t.id, "ghost")             # 跨域校验仍生效


@pytest.mark.asyncio
async def test_validate_username_reads_file_layer_not_session(monkeypatch, tmp_path):
    """file 模式:_validate 走文件层。反向种子证非假绿——
    follow 只进 DB session 时应被拒,只进文件层时应通过。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    s = async_sessionmaker(engine, expire_on_commit=False)()
    # 反向种子:DB session 有 in_db_only,文件层有 in_file_only
    s.add(ScraperFollow(username="in_db_only", reason="t", added_by="t"))
    await s.commit()
    from src.preference.infrastructure.file_follow_repository import FileFollowStore
    await FileFollowStore(tmp_path).create_scraper_follow("in_file_only", "t", "t")

    svc = TopicService()
    t = await svc.create_topic(s, name="AI")
    # 文件层的 in_file_only 通过(证走文件层)
    acct = await svc.add_account(s, t.id, "in_file_only")
    assert acct.username == "in_file_only"
    # DB session 的 in_db_only 被拒(证不再读 session)
    with pytest.raises(ValueError, match="未在系统抓取列表中注册"):
        await svc.add_account(s, t.id, "in_db_only")
    await s.close()
    await engine.dispose()
