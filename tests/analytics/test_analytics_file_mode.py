"""analytics get_posting_frequency 在 XWATCHER_DATA_LAYER=file 下走文件层。
路径可证:种子只进文件层;槽语义钉死生产 PG round-half-up(非 SQLite floor,见
test_slot_rounds_to_nearest_like_pg——analytics 无 se oracle,以 PG 语义钉值为等价证据)。"""
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
async def test_slot_rounds_to_nearest_like_pg(monkeypatch, tmp_path):
    """槽边界 = 四舍五入到最近 30 分钟(复刻生产 PG `cast(local_epoch/1800,int)*1800` 进位语义),
    非截断。⚠️ SQLite 整数除法=floor≠PG,故不能用 SQLite-sqlalchemy 当等价 oracle
    (实测 PG vs SQLite:E%1800>=900 时 PG 进位/SQLite floor)——本测试用同一 30 分钟槽内
    前半段/半点/后半段三条推文钉死 round-half-up:floor bug 会把三条都归前一槽 → 翻红。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    # 基准对齐到 30 分钟槽边界(:00 或 :30,second=0 → epoch%1800==0),取 2h 前确保在窗内
    base = (now - timedelta(hours=2)).replace(second=0, microsecond=0)
    base = base - timedelta(minutes=base.minute % 30)
    t_down = base + timedelta(minutes=10)   # %1800=600 <900 → 归 base 槽(floor/round 一致)
    t_half = base + timedelta(minutes=15)   # %1800=900 → PG round-half-up → 归 base+30min 槽
    t_up = base + timedelta(minutes=20)     # %1800=1200 >=900 → 归 base+30min 槽
    topic_id = await _seed_file(tmp_path, ["analyst_a"], [
        ("rd_1", "analyst_a", t_down),
        ("rd_2", "analyst_a", t_half),
        ("rd_3", "analyst_a", t_up),
    ])
    from src.data_layer.provider import get_analytics_repo

    res = await get_analytics_repo().get_posting_frequency(topic_id=topic_id, tz_offset=0, slots=50)
    label_down = base.strftime("%Y-%m-%d %H:%M")
    label_up = (base + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
    slots = {d["slot"]: d["count"] for d in res["distribution"]}
    # round-half-up:t_down 归 base 槽,t_half+t_up 进位归 base+30min 槽。
    # floor bug 会得 {label_down: 3} → 本断言翻红。
    assert slots == {label_down: 1, label_up: 2}, f"得到 {slots}(floor bug 会是 {{{label_down}: 3}})"
    assert res["total_tweets"] == 3


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
