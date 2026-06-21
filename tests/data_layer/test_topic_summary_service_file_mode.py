"""topic_summary_service 任务/摘要持久化在 file 模式走文件层。
绕开 LLM 与 _query_tweets(跨域):测 save_external_summary / get_task / list_tasks /
get_latest_summary / delete_task / create_and_execute_task(patch asyncio.create_task)。"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database.models import Base
from src.topic.services.topic_service import TopicService
from src.topic.services.topic_summary_service import TopicSummaryService
from src.topic.domain.models import TopicSummaryTaskStatus


@pytest_asyncio.fixture
async def session(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    s = async_sessionmaker(engine, expire_on_commit=False)()
    yield s
    await s.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_external_summary_and_queries_file_mode(session, tmp_path):
    topic = await TopicService().create_topic(session, name="AI")
    svc = TopicSummaryService(providers=[])      # 不触 LLM
    task = await svc.save_external_summary(
        session, topic_id=topic.id, content="report", time_span_hours=24,
        deadline=datetime(2026, 1, 1), tz_offset=0, tweet_count=3, account_count=1)
    assert task.status == TopicSummaryTaskStatus.completed
    assert task.summary is not None and task.summary.content == "report"
    # 文件层路由可证:task/summary 落盘 topics.json(非 DB)
    assert (tmp_path / "topics" / "topics.json").exists()
    # 查询面
    got = await svc.get_task(session, task.id)
    assert got.id == task.id and got.summary.content == "report"
    assert len(await svc.list_tasks(session, topic_id=topic.id)) == 1
    latest = await svc.get_latest_summary(session, topic.id)
    assert latest.id == task.id
    assert await svc.delete_task(session, task.id) is True
    assert await svc.get_task(session, task.id) is None


@pytest.mark.asyncio
async def test_create_and_execute_task_returns_pending_file_mode(session):
    from src.data_layer.provider import get_topic_store
    topic = await TopicService().create_topic(session, name="AI")
    # 该方法要求主题有关联账号:用 file 模式 store 直接加(绕开 _validate 的 ScraperFollow 依赖)
    await get_topic_store(session).add_account(topic.id, "alice")
    await session.commit()
    svc = TopicSummaryService(providers=[])
    # session_factory 仅 _execute_task 用,而 asyncio.create_task 被 patch → 后台不跑,factory 不被调用
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    with patch("src.topic.services.topic_summary_service.asyncio.create_task"):
        task = await svc.create_and_execute_task(
            session, factory, topic_id=topic.id, time_span_hours=24,
            deadline=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert task.status == TopicSummaryTaskStatus.pending
    assert task.topic_name == "AI" and task.summary is None
