"""analytics get_posting_frequency 在 XWATCHER_DATA_LAYER=file 下走文件层。
路径可证:种子只进文件层;跨模式等价:同数据 file vs sqlalchemy 同 distribution(替代无 se oracle)。"""
import re
from datetime import datetime, timedelta, timezone

import pytest


async def _seed_file(tmp_path, accounts, specs):
    """种子 topic+accounts+tweets 进文件层。specs=[(tweet_id, author, created_at)]。返回 topic_id。"""
    from src.scraper.domain.models import Tweet
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    from src.topic.infrastructure.file_topic_repository import FileTopicStore

    tstore = FileTopicStore(tmp_path)
    topic = await tstore.create(name="t", description=None, user_id=0)
    for acc in accounts:
        await tstore.add_account(topic.id, acc)
    await FileTweetStore(tmp_path).save_tweets(
        [Tweet(tweet_id=t, text="x", created_at=c, author_username=a) for (t, a, c) in specs],
        early_stop_threshold=0,
    )
    return topic.id


@pytest.mark.asyncio
async def test_file_mode_total_and_window(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    topic_id = await _seed_file(tmp_path, ["analyst_a", "analyst_b"], [
        ("at_1", "analyst_a", now - timedelta(minutes=5)),
        ("at_2", "analyst_a", now - timedelta(minutes=35)),
        ("at_3", "analyst_b", now - timedelta(minutes=40)),
        ("at_4", "analyst_b", now - timedelta(minutes=95)),
    ])
    from src.data_layer.provider import get_analytics_repo

    res = await get_analytics_repo().get_posting_frequency(topic_id=topic_id, tz_offset=0, slots=50)
    assert res["total_tweets"] == 4
    for d in res["distribution"]:
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", d["slot"])
        assert int(d["slot"][-2:]) in (0, 30)
    assert sum(d["count"] for d in res["distribution"]) == 4
    res2 = await get_analytics_repo().get_posting_frequency(topic_id=topic_id, tz_offset=0, slots=2)
    assert res2["total_tweets"] == 3


@pytest.mark.asyncio
async def test_file_mode_empty_topic(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    topic_id = await _seed_file(tmp_path, [], [])
    from src.data_layer.provider import get_analytics_repo

    res = await get_analytics_repo().get_posting_frequency(topic_id=topic_id, tz_offset=0, slots=50)
    assert res["distribution"] == []
    assert res["total_tweets"] == 0
    assert "time_range_start" in res and "time_range_end" in res


@pytest.mark.asyncio
async def test_cross_mode_equivalence(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    accounts = ["analyst_a", "ANALYST_B"]
    specs = [
        ("at_1", "analyst_a", now - timedelta(minutes=5)),
        ("at_2", "analyst_a", now - timedelta(minutes=35)),
        ("at_3", "analyst_b", now - timedelta(minutes=40)),
        ("at_4", "analyst_b", now - timedelta(minutes=95)),
        ("at_5", "analyst_b", now - timedelta(minutes=600)),
    ]
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    topic_id = await _seed_file(tmp_path, accounts, specs)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.database.models import Base
    from src.scraper.infrastructure.models import TweetOrm
    from src.topic.infrastructure.models import TopicAccountOrm, TopicOrm

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    session.add(TopicOrm(id=topic_id, name="t", user_id=0))
    await session.flush()
    for acc in accounts:
        session.add(TopicAccountOrm(topic_id=topic_id, username=acc))
    for (t, a, c) in specs:
        session.add(TweetOrm(tweet_id=t, text="x", created_at=c, db_created_at=now,
                             author_username=a, author_display_name=None, media=None))
    await session.commit()

    from src.data_layer.provider import get_analytics_repo

    for tz in (0, -480):
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        file_res = await get_analytics_repo().get_posting_frequency(topic_id=topic_id, tz_offset=tz, slots=50)
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
        sql_res = await get_analytics_repo(session).get_posting_frequency(topic_id=topic_id, tz_offset=tz, slots=50)
        assert file_res["distribution"] == sql_res["distribution"], f"tz={tz} 不等"
        assert file_res["total_tweets"] == sql_res["total_tweets"]

    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_mcp_tool_file_mode(monkeypatch, tmp_path):
    """MCP get_posting_frequency 工具 file 模式走文件层(路径可证)。"""
    import json

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    topic_id = await _seed_file(tmp_path, ["analyst_a"], [
        ("mt_1", "analyst_a", now - timedelta(minutes=5)),
        ("mt_2", "analyst_a", now - timedelta(minutes=10)),
    ])
    from mcp.server.fastmcp import FastMCP

    from src.mcp.tools import analytics_tools

    mcp = FastMCP("test")
    analytics_tools.register(mcp)
    fn = mcp._tool_manager._tools["get_posting_frequency"].fn
    raw = await fn(topic_id=topic_id, tz_offset=0, slots=50)
    data = json.loads(raw)
    assert data["success"] is True
    assert data["data"]["total_tweets"] == 2
