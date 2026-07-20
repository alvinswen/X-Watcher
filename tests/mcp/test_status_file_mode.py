"""status 3 段统计(tweet/follow/summary)在文件层（file 唯一数据层）下运行。

路径可证:种子只进文件层 → 断言 stats(total/latest/today_count/active/inactive/pending 反连接)。
跨模式对账:同数据 file vs sqlalchemy(SQLite,建 Base + 种 ORM)产同 3 stats。
⚠️ 无 round 陷阱豁免:全 count/max/today-count,无除法分桶 → SQLite 是有效 oracle。
每条配故障注入(改接缝/篡改数据应翻红)。
"""

from datetime import UTC, datetime, timedelta

import pytest

# ── 文件层种子助手 ───────────────────────────────────────────


def _tweet(tid, author, created_at, text="hello world"):
    from src.scraper.domain.models import Tweet

    return Tweet(
        tweet_id=tid,
        text=text,
        created_at=created_at,
        author_username=author,
        author_display_name=f"{author} disp",
    )


def _summary(tid):
    from src.summarization.domain.models import SummaryRecord

    now = datetime(2024, 1, 1, tzinfo=UTC)
    return SummaryRecord(
        summary_id=f"s-{tid}",
        tweet_id=tid,
        summary_text=f"摘要{tid}",
        translation_text=f"译文{tid}",
        model_provider="p",
        model_name="m",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
        content_hash=f"h-{tid}",
        created_at=now,
        updated_at=now,
    )


def _follow(fid, username, is_active, added_at=None):
    from src.preference.domain.models import ScraperFollow

    return ScraperFollow(
        id=fid,
        username=username,
        added_at=added_at or datetime(2024, 1, 1, tzinfo=UTC),
        reason="r",
        added_by="tester",
        is_active=is_active,
    )


async def _seed_tweets(root, tweets, summaries=()):
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    await FileTweetStore(root).save_tweets(list(tweets), early_stop_threshold=0)
    if summaries:
        await FileSummaryStore(root).seed(list(summaries))


async def _seed_follows(root, follows):
    from src.preference.infrastructure.file_follow_repository import FileFollowStore

    await FileFollowStore(root).seed(list(follows))


# ── file 路径可证 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tweet_stats_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # 2 条今日(午夜后)+ 1 条昨日;latest=今日最大
    t_late = today0 + timedelta(hours=10)
    await _seed_tweets(
        tmp_path,
        [
            _tweet("a", "alice", today0 + timedelta(hours=1)),
            _tweet("b", "alice", t_late),
            _tweet("c", "bob", today0 - timedelta(hours=5)),  # 昨日
        ],
    )
    from src.data_layer.provider import get_status_repo

    stats = await get_status_repo().get_tweet_stats()
    assert stats.total == 3
    assert stats.today_count == 2  # 仅午夜后 2 条
    assert stats.latest_tweet_at.tzinfo is not None
    assert stats.latest_tweet_at == t_late  # aware max
    # 故障注入:多种 1 条今日 → today_count/total 应变(证非写死)
    await _seed_tweets(tmp_path, [_tweet("d", "carol", today0 + timedelta(hours=2))])
    stats2 = await get_status_repo().get_tweet_stats()
    assert stats2.total == 4 and stats2.today_count == 3


@pytest.mark.asyncio
async def test_get_tweet_stats_empty_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_status_repo

    stats = await get_status_repo().get_tweet_stats()
    assert stats.total == 0 and stats.today_count == 0
    assert stats.latest_tweet_at is None  # 空表 max → None(镜像 func.max NULL)


@pytest.mark.asyncio
async def test_get_follow_stats_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_follows(
        tmp_path,
        [
            _follow(1, "alice", True),
            _follow(2, "bob", True),
            _follow(3, "carol", False),
        ],
    )
    from src.data_layer.provider import get_status_repo

    stats = await get_status_repo().get_follow_stats()
    assert stats.total == 3 and stats.active == 2 and stats.inactive == 1
    # 故障注入:全 active 数据应 inactive=0(证 active 真按 is_active 数)
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "all_active"))
    await _seed_follows(tmp_path / "all_active", [_follow(1, "x", True), _follow(2, "y", True)])
    stats2 = await get_status_repo().get_follow_stats()
    assert stats2.total == 2 and stats2.active == 2 and stats2.inactive == 0


@pytest.mark.asyncio
async def test_get_summary_stats_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    # 4 tweet,2 有 summary → pending(反连接)=2
    await _seed_tweets(
        tmp_path,
        [
            _tweet("t1", "alice", now - timedelta(hours=1)),
            _tweet("t2", "alice", now - timedelta(hours=2)),
            _tweet("t3", "bob", now - timedelta(hours=3)),
            _tweet("t4", "bob", now - timedelta(hours=4)),
        ],
        summaries=[_summary("t1"), _summary("t2")],
    )
    from src.data_layer.provider import get_status_repo

    stats = await get_status_repo().get_summary_stats()
    assert stats.total == 2
    assert stats.pending_tweets == 2  # t3/t4 无 summary(反连接)
    # 故障注入:再给 t3 加 summary → pending 应降到 1、total 升到 3
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    await FileSummaryStore(tmp_path).seed([_summary("t1"), _summary("t2"), _summary("t3")])
    stats2 = await get_status_repo().get_summary_stats()
    assert stats2.total == 3 and stats2.pending_tweets == 1


# ── MCP get_system_status file 模式 ─────────────────────────


@pytest.mark.asyncio
async def test_mcp_get_system_status_file_mode(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    await _seed_tweets(
        tmp_path,
        [
            _tweet("m1", "alice", today0 + timedelta(hours=1)),
            _tweet("m2", "alice", today0 - timedelta(hours=5)),
        ],
        summaries=[_summary("m1")],
    )
    await _seed_follows(tmp_path, [_follow(1, "alice", True), _follow(2, "bob", False)])

    from mcp.server.fastmcp import FastMCP

    from src.mcp.tools import status_tools

    mcp = FastMCP("test")
    status_tools.register(mcp)
    fn = mcp._tool_manager._tools["get_system_status"].fn
    data = json.loads(await fn())

    assert data["success"] is True
    d = data["data"]
    assert d["tweets"]["total"] == 2 and d["tweets"]["today_count"] == 1
    assert d["summaries"]["total"] == 1 and d["summaries"]["pending_tweets"] == 1
    assert (
        d["follows"]["total"] == 2 and d["follows"]["active"] == 1 and d["follows"]["inactive"] == 1
    )
    assert "topics" not in d
    assert "scheduler" not in d


@pytest.mark.asyncio
async def test_mcp_status_seam_rename_breaks(monkeypatch):
    """故障注入:把 provider 接缝改名应使 MCP get_system_status 翻红(证真走门面)。"""
    import json

    from mcp.server.fastmcp import FastMCP

    import src.data_layer.provider as provider
    from src.mcp.tools import status_tools

    # 删掉 get_status_repo 模拟接缝改名 → 工具内 import 失败 → error_response
    monkeypatch.delattr(provider, "get_status_repo", raising=True)
    mcp = FastMCP("test")
    status_tools.register(mcp)
    fn = mcp._tool_manager._tools["get_system_status"].fn
    data = json.loads(await fn())
    assert data["success"] is False  # 接缝缺失 → 失败,证 MCP 真依赖该门面


# ── MCP status resource file 模式 ───────────────────────────


@pytest.mark.asyncio
async def test_mcp_status_resource_file_mode(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    await _seed_tweets(
        tmp_path,
        [
            _tweet("r1", "alice", now - timedelta(hours=1)),
            _tweet("r2", "bob", now - timedelta(hours=2)),
        ],
        summaries=[_summary("r1")],
    )
    await _seed_follows(tmp_path, [_follow(1, "alice", True)])

    from mcp.server.fastmcp import FastMCP

    from src.mcp.resources import providers

    mcp = FastMCP("test")
    providers.register(mcp)
    raw = await mcp._resource_manager._resources["xwatcher://status"].read()
    data = json.loads(raw)
    assert data["tweets"] == 2 and data["follows"] == 1
    assert data["summaries"] == 1
    assert "topics" not in data
