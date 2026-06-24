"""status 3 段统计(tweet/follow/summary)在 XWATCHER_DATA_LAYER=file 下走文件层。

路径可证:种子只进文件层 → 断言 stats(total/latest/today_count/active/inactive/pending 反连接)。
跨模式对账:同数据 file vs sqlalchemy(SQLite,建 Base + 种 ORM)产同 3 stats。
⚠️ 无 round 陷阱豁免:全 count/max/today-count,无除法分桶 → SQLite 是有效 oracle。
每条配故障注入(改接缝/篡改数据应翻红)。
"""

from datetime import datetime, timedelta, timezone

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

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
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
        added_at=added_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
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
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
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
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_status_repo

    stats = await get_status_repo().get_tweet_stats()
    assert stats.total == 0 and stats.today_count == 0
    assert stats.latest_tweet_at is None  # 空表 max → None(镜像 func.max NULL)


@pytest.mark.asyncio
async def test_get_follow_stats_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
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
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
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


# ── 跨模式对账(file vs sqlalchemy SQLite)────────────────────


async def _build_sqlite_session():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.database.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    return engine, session


def _norm_instant(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@pytest.mark.asyncio
async def test_cross_mode_status_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite)产同 3 stats(时间按 instant 归一比)。"""
    now = datetime.now(timezone.utc)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t_late = today0 + timedelta(hours=8)
    tweet_specs = [
        ("a", "alice", today0 + timedelta(hours=1)),
        ("b", "alice", t_late),
        ("c", "bob", today0 - timedelta(hours=6)),  # 昨日
        ("d", "bob", today0 - timedelta(hours=7)),  # 昨日
    ]
    sum_tids = ["a", "b"]  # pending = c,d = 2
    follow_specs = [(1, "alice", True), (2, "bob", True), (3, "carol", False)]

    # ── 文件层种子 ──
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(
        tmp_path,
        [_tweet(t, a, c) for (t, a, c) in tweet_specs],
        summaries=[_summary(t) for t in sum_tids],
    )
    await _seed_follows(tmp_path, [_follow(i, u, act) for (i, u, act) in follow_specs])

    # ── sqlalchemy(SQLite)种子 ──
    from src.database.models import ScraperFollow as ScraperFollowOrm
    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm

    engine, session = await _build_sqlite_session()
    for t, a, c in tweet_specs:
        session.add(
            TweetOrm(
                tweet_id=t,
                text="x",
                created_at=c.replace(tzinfo=None),
                db_created_at=now.replace(tzinfo=None),
                author_username=a,
                author_display_name=f"{a} disp",
                media=None,
            )
        )
    for t in sum_tids:
        session.add(
            SummaryOrm(
                summary_id=f"s-{t}",
                tweet_id=t,
                summary_text=f"摘要{t}",
                translation_text=f"译文{t}",
                content_hash=f"h-{t}",
                model_provider="p",
                model_name="m",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                cost_usd=0.0,
            )
        )
    for i, u, act in follow_specs:
        session.add(
            ScraperFollowOrm(
                id=i,
                username=u,
                reason="r",
                added_by="tester",
                is_active=act,
                added_at=datetime(2024, 1, 1),
            )
        )
    await session.commit()

    from src.data_layer.provider import get_status_repo

    # tweet
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_tw = await get_status_repo().get_tweet_stats()
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_tw = await get_status_repo(session).get_tweet_stats()
    assert f_tw.total == s_tw.total == 4
    assert f_tw.today_count == s_tw.today_count == 2
    assert _norm_instant(f_tw.latest_tweet_at) == _norm_instant(s_tw.latest_tweet_at)

    # follow
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_fl = await get_status_repo().get_follow_stats()
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_fl = await get_status_repo(session).get_follow_stats()
    assert (
        (f_fl.total, f_fl.active, f_fl.inactive)
        == (s_fl.total, s_fl.active, s_fl.inactive)
        == (3, 2, 1)
    )

    # summary
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_su = await get_status_repo().get_summary_stats()
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_su = await get_status_repo(session).get_summary_stats()
    assert (f_su.total, f_su.pending_tweets) == (s_su.total, s_su.pending_tweets) == (2, 2)

    await session.close()
    await engine.dispose()


# ── MCP get_system_status file 模式 ─────────────────────────


@pytest.mark.asyncio
async def test_mcp_get_system_status_file_mode(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
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

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    from mcp.server.fastmcp import FastMCP
    from src.mcp.tools import status_tools
    import src.data_layer.provider as provider

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

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
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
