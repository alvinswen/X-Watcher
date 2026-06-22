"""SqlalchemyTopicStore / SqlalchemyTopicSummaryTaskStore:domain 接口 + 延迟 commit。"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database.models import Base
from src.data_layer._topic_sqlalchemy import SqlalchemyTopicStore, SqlalchemyTopicSummaryTaskStore
from src.topic.domain.models import TopicSummaryTaskStatus


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    s = async_sessionmaker(engine, expire_on_commit=False)()
    yield s
    await s.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_returns_domain_and_defers_commit(session):
    store = SqlalchemyTopicStore(session)
    topic = await store.create(name="AI", description="d", user_id=None)
    assert topic.id is not None and topic.name == "AI"        # 返回域模型
    # 延迟 commit:adapter 未 commit,数据仅 flush 在事务内;rollback 应丢弃
    await session.rollback()
    assert await store.get_by_name("AI") is None


@pytest.mark.asyncio
async def test_update_mutates_and_returns_domain(session):
    store = SqlalchemyTopicStore(session)
    t = await store.create(name="AI", description="d")
    await session.commit()
    t.name = "ML"
    r = await store.update(t)
    await session.commit()
    assert r.name == "ML"
    assert (await store.get_by_name("ML")).id == t.id


@pytest.mark.asyncio
async def test_replace_accounts_roundtrip(session):
    store = SqlalchemyTopicStore(session)
    t = await store.create(name="AI")
    await session.commit()
    await store.replace_accounts(t.id, ["alice", "bob"])
    await session.commit()
    accts = await store.get_accounts(t.id)
    assert sorted(a.username for a in accts) == ["alice", "bob"]


@pytest.mark.asyncio
async def test_task_store_create_update_with_enum_status(session):
    tstore = SqlalchemyTopicStore(session)
    t = await tstore.create(name="AI")
    await session.commit()
    store = SqlalchemyTopicSummaryTaskStore(session)
    from datetime import datetime
    task = await store.create_task(topic_id=t.id, time_span_hours=24,
                                   deadline=datetime(2026, 1, 1), status="pending")
    await session.commit()
    assert task.topic_name == "AI" and task.summary is None      # 含派生字段
    task.status = TopicSummaryTaskStatus.running                 # 设枚举(非字符串)
    r = await store.update_task(task)
    await session.commit()
    assert r.status == TopicSummaryTaskStatus.running
    s = await store.create_summary(task_id=task.id, content="x",
                                   llm_provider="p", llm_model="m")
    await session.commit()
    assert s.task_id == task.id
    got = await store.get_task(task.id)
    assert got.summary is not None and got.summary.content == "x"
