"""topic_service 在 XWATCHER_DATA_LAYER=file 下走文件层(topic 自有数据)。
跨域校验 _validate_username_in_scraper_follows 用真 session 预置 ScraperFollow。"""
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
    # 跨域校验依赖 scraper_follows(走 session,与 topic 文件层无关)
    # ScraperFollow.reason / added_by 非空无默认 → 补最小必填字段使 commit 成功
    s.add(ScraperFollow(username="alice", reason="test", added_by="test"))
    await s.commit()
    yield s
    await s.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_topic_crud_and_accounts_file_mode(session):
    svc = TopicService()
    t = await svc.create_topic(session, name="AI", description="d")
    assert t.id is not None
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
