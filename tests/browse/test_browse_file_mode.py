"""browse get_tweets/get_author_timeline 在 XWATCHER_DATA_LAYER=file 下走文件层。
路径可证:种子只进文件层;跨模式对账:同数据 file vs sqlalchemy 同 (items,total)/author_meta
(browse 列表无聚合 div/cast→SQLite 是有效 oracle;seed distinct created_at 避 tie-break)。"""
from datetime import datetime, timedelta, timezone

import pytest


def _tweet(tid, author, created_at, text="hello world"):
    from src.scraper.domain.models import Tweet
    return Tweet(tweet_id=tid, text=text, created_at=created_at, author_username=author,
                 author_display_name=f"{author} disp")


def _summary(tid):
    from src.summarization.domain.models import SummaryRecord
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return SummaryRecord(summary_id=f"s-{tid}", tweet_id=tid, summary_text=f"摘要{tid}",
                         translation_text=f"译文{tid}", model_provider="p", model_name="m",
                         prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0,
                         content_hash=f"h-{tid}", created_at=now, updated_at=now)


async def _seed_file(tmp_path, tweets, summaries=(), follows=()):
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
    from src.preference.infrastructure.file_follow_repository import FileFollowStore
    await FileTweetStore(tmp_path).save_tweets(list(tweets), early_stop_threshold=0)
    if summaries:
        await FileSummaryStore(tmp_path).seed(list(summaries))
    for (u, reason) in follows:
        await FileFollowStore(tmp_path).create_scraper_follow(u, reason, "admin")


@pytest.mark.asyncio
async def test_get_tweets_file_mode_join_and_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
    date_str = base.strftime("%Y-%m-%d")
    await _seed_file(tmp_path, [
        _tweet("t1", "alice", base + timedelta(minutes=1)),
        _tweet("t2", "alice", base + timedelta(minutes=2)),
        _tweet("t3", "bob", base + timedelta(minutes=3)),
    ], summaries=[_summary("t2")])
    from src.data_layer.provider import get_browse_repo

    items, total = await get_browse_repo().get_tweets(date_str, None, page=1, page_size=20, tz_offset=0)
    assert total == 3
    assert [i["tweet_id"] for i in items] == ["t1", "t2", "t3"]
    by_id = {i["tweet_id"]: i for i in items}
    assert by_id["t2"]["summary_text"] == "摘要t2" and by_id["t2"]["translation_text"] == "译文t2"
    assert by_id["t1"]["summary_text"] is None
    assert set(by_id["t1"]) == {"tweet_id","created_at","author_username","author_display_name",
        "summary_text","translation_text","text","reference_type","referenced_tweet_id",
        "referenced_tweet_text","referenced_tweet_author_username","media","referenced_tweet_media"}
    items2, total2 = await get_browse_repo().get_tweets(date_str, "ALICE", page=1, page_size=20, tz_offset=0)
    assert total2 == 2 and {i["tweet_id"] for i in items2} == {"t1", "t2"}


@pytest.mark.asyncio
async def test_get_author_timeline_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=2); until = now + timedelta(days=1)
    await _seed_file(tmp_path, [
        _tweet("a1", "alice", now - timedelta(hours=3)),
        _tweet("a2", "alice", now - timedelta(hours=1)),
    ], summaries=[_summary("a2")], follows=[("alice", "AI 研究者")])
    from src.data_layer.provider import get_browse_repo

    meta, items, total = await get_browse_repo().get_author_timeline("alice", since, until, page=1, page_size=20)
    assert total == 2
    assert [i["tweet_id"] for i in items] == ["a2", "a1"]
    assert meta == {"author_username": "alice", "author_display_name": "alice disp", "reason": "AI 研究者"}
    assert items[0]["summary_text"] == "摘要a2"


@pytest.mark.asyncio
async def test_get_tweets_file_mode_media_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    import json
    from src.scraper.domain.models import Media, Tweet
    now = datetime.now(timezone.utc)
    base = now.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
    tw = Tweet(tweet_id="m1", text="x", created_at=base + timedelta(minutes=1), author_username="alice",
               media=[Media(media_key="k1", type="photo")])
    await _seed_file(tmp_path, [tw])
    from src.data_layer.provider import get_browse_repo

    items, _ = await get_browse_repo().get_tweets(base.strftime("%Y-%m-%d"), None, page=1, page_size=20, tz_offset=0)
    assert isinstance(items[0]["media"], list) and isinstance(items[0]["media"][0], dict)
    # exclude_none 匹配生产 pg(from_domain 以 exclude_none 持久化 media):只含已设字段,
    # 不含 preview_image_url/alt_text:null。Media(media_key,type) 其余 None → 恰 2 键。
    assert items[0]["media"][0] == {"media_key": "k1", "type": "photo"}
    # MCP 路径经 success_response 的 json.dumps(default=_default_serializer);datetime→isoformat
    # 兜底,其余必须已是 plain JSON 类型(media→dict)。逐字复刻该契约,而非裸 json.dumps。
    from src.mcp.helpers import _default_serializer
    json.dumps(items, default=_default_serializer)


@pytest.mark.asyncio
async def test_pagination_and_empty_file_mode(monkeypatch, tmp_path):
    """应用层分页(offset 切片)≡ 预期 + total 全量计数 + 空结果分支(M3 钉 off-by-one)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
    date_str = base.strftime("%Y-%m-%d")
    await _seed_file(tmp_path, [_tweet(f"p{i}", "alice", base + timedelta(minutes=i)) for i in range(1, 4)],
                     follows=[("alice", "r")])
    from src.data_layer.provider import get_browse_repo

    p1, t1 = await get_browse_repo().get_tweets(date_str, None, page=1, page_size=2, tz_offset=0)
    p2, t2 = await get_browse_repo().get_tweets(date_str, None, page=2, page_size=2, tz_offset=0)
    assert t1 == t2 == 3                       # total 全量计数不随页变
    assert [i["tweet_id"] for i in p1] == ["p1", "p2"]   # ASC 第 1 页
    assert [i["tweet_id"] for i in p2] == ["p3"]          # 第 2 页(offset=2 切片正确,无 off-by-one)
    # 空结果:无推文日期
    empty, et = await get_browse_repo().get_tweets("1999-01-01", None, page=1, page_size=20, tz_offset=0)
    assert empty == [] and et == 0
    # author_timeline 空 → display_name=None / items=[]
    meta, items, total = await get_browse_repo().get_author_timeline(
        "ghost", base - timedelta(days=1), base + timedelta(days=1), page=1, page_size=20)
    assert items == [] and total == 0 and meta["author_display_name"] is None


@pytest.mark.asyncio
async def test_mcp_browse_tweets_file_mode(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
    await _seed_file(tmp_path, [_tweet("mb1", "alice", base + timedelta(minutes=1)),
                                _tweet("mb2", "alice", base + timedelta(minutes=2))],
                     summaries=[_summary("mb2")])
    from mcp.server.fastmcp import FastMCP
    from src.mcp.tools import browse_tools
    mcp = FastMCP("test"); browse_tools.register(mcp)
    fn = mcp._tool_manager._tools["browse_tweets"].fn
    raw = await fn(date=base.strftime("%Y-%m-%d"), tz_offset=0)
    data = json.loads(raw)
    assert data["success"] is True
    assert data["data"]["total"] == 2 and data["data"]["count"] == 2
    assert {i["tweet_id"] for i in data["data"]["items"]} == {"mb1", "mb2"}


@pytest.mark.asyncio
async def test_get_daily_stats_file_mode_basic(monkeypatch, tmp_path):
    """月窗按本地日分组计数,升序;空日不出现。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    # tz_offset=0(UTC):2026-05-02 两条 / 2026-05-04 一条
    await _seed_file(tmp_path, [
        _tweet("d1", "alice", datetime(2026, 5, 2, 3, 0, tzinfo=timezone.utc)),
        _tweet("d2", "bob", datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc)),
        _tweet("d3", "alice", datetime(2026, 5, 4, 1, 0, tzinfo=timezone.utc)),
    ])
    from src.data_layer.provider import get_browse_repo
    days = await get_browse_repo().get_daily_stats(2026, 5, tz_offset=0)
    assert days == [{"date": "2026-05-02", "count": 2}, {"date": "2026-05-04", "count": 1}]


@pytest.mark.asyncio
async def test_get_daily_stats_tz_offset_boundary(monkeypatch, tmp_path):
    """tz_offset 把跨 UTC 午夜的推文归到正确本地日(故障注入:偏移符号反向则归错日)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    # tz_offset=-480(China UTC+8):local=UTC+8h
    # UTC 2026-05-01 15:00 → local 2026-05-01 23:00 → 本地日 05-01
    # UTC 2026-05-01 17:00 → local 2026-05-02 01:00 → 本地日 05-02
    await _seed_file(tmp_path, [
        _tweet("b1", "alice", datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)),
        _tweet("b2", "alice", datetime(2026, 5, 1, 17, 0, tzinfo=timezone.utc)),
    ])
    from src.data_layer.provider import get_browse_repo
    days = await get_browse_repo().get_daily_stats(2026, 5, tz_offset=-480)
    assert days == [{"date": "2026-05-01", "count": 1}, {"date": "2026-05-02", "count": 1}]


@pytest.mark.asyncio
async def test_get_daily_stats_min_text_length(monkeypatch, tmp_path):
    """min_text_length 过滤短文本(故障注入:不过滤则短文本计入)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [
        _tweet("s1", "alice", datetime(2026, 5, 2, 3, 0, tzinfo=timezone.utc), text="hi"),       # len 2
        _tweet("s2", "alice", datetime(2026, 5, 2, 4, 0, tzinfo=timezone.utc), text="hello!!"),  # len 7
    ])
    from src.data_layer.provider import get_browse_repo
    days = await get_browse_repo().get_daily_stats(2026, 5, tz_offset=0, min_text_length=5)
    assert days == [{"date": "2026-05-02", "count": 1}]


@pytest.mark.asyncio
async def test_get_daily_stats_december_cross_year(monkeypatch, tmp_path):
    """12 月跨年分支(month==12→local_end=次年1月);次年 1 月推文不计入。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [
        _tweet("dc1", "alice", datetime(2026, 12, 31, 3, 0, tzinfo=timezone.utc)),
        _tweet("dc2", "alice", datetime(2027, 1, 1, 3, 0, tzinfo=timezone.utc)),  # 次年,不计入
    ])
    from src.data_layer.provider import get_browse_repo
    days = await get_browse_repo().get_daily_stats(2026, 12, tz_offset=0)
    assert days == [{"date": "2026-12-31", "count": 1}]


@pytest.mark.asyncio
async def test_get_daily_stats_empty_month(monkeypatch, tmp_path):
    """空月返回 [](窗口排除其它月推文)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [_tweet("x", "alice", datetime(2026, 5, 2, 3, 0, tzinfo=timezone.utc))])
    from src.data_layer.provider import get_browse_repo
    days = await get_browse_repo().get_daily_stats(2026, 7, tz_offset=0)  # 7 月无推文
    assert days == []


@pytest.mark.asyncio
async def test_get_authors_file_mode_basic(monkeypatch, tmp_path):
    """按作者分组(count+max),按 max DESC 排序,last_tweet_at aware,reason 命中 active follow。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    day = datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc)
    await _seed_file(tmp_path, [
        _tweet("g1", "alice", day),                          # alice max 03:00
        _tweet("g2", "alice", day.replace(hour=5)),          # alice max→05:00 count 2
        _tweet("g3", "bob", day.replace(hour=8)),            # bob max 08:00 count 1(最新→排第一)
    ], follows=[("alice", "AI 研究者")])  # bob 无 follow
    from src.data_layer.provider import get_browse_repo
    authors = await get_browse_repo().get_authors("2026-05-10", tz_offset=0)
    assert [a["author_username"] for a in authors] == ["bob", "alice"]   # max DESC:bob 08:00 > alice 05:00
    alice = next(a for a in authors if a["author_username"] == "alice")
    assert alice["tweet_count"] == 2
    assert alice["last_tweet_at"] == day.replace(hour=5)                  # aware max
    assert alice["last_tweet_at"].tzinfo is not None                     # 钉 aware(MCP isoformat +00:00)
    assert alice["author_display_name"] == "alice disp"
    assert alice["reason"] == "AI 研究者"
    bob = next(a for a in authors if a["author_username"] == "bob")
    assert bob["reason"] is None                                         # 无 follow→None
    assert set(alice) == {"author_username", "author_display_name", "tweet_count", "last_tweet_at", "reason"}


@pytest.mark.asyncio
async def test_get_authors_display_name_latest_and_min_len(monkeypatch, tmp_path):
    """display_name 取当日最新一条;min_text_length 过滤(故障注入:取最早 / 不过滤则翻红)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.scraper.domain.models import Tweet
    day = datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc)
    await _seed_file(tmp_path, [
        Tweet(tweet_id="n1", text="hello world", created_at=day, author_username="alice",
              author_display_name="OLD NAME"),
        Tweet(tweet_id="n2", text="hello world", created_at=day.replace(hour=6), author_username="alice",
              author_display_name="NEW NAME"),                            # 最新→display_name 取此
        Tweet(tweet_id="n3", text="hi", created_at=day.replace(hour=7), author_username="alice"),  # len 2 被过滤
    ])
    from src.data_layer.provider import get_browse_repo
    authors = await get_browse_repo().get_authors("2026-05-10", tz_offset=0, min_text_length=5)
    assert len(authors) == 1
    assert authors[0]["tweet_count"] == 2                                # n3 被 min_len 过滤
    assert authors[0]["author_display_name"] == "NEW NAME"               # 当日最新(n2),非最早(n1)
    assert authors[0]["last_tweet_at"] == day.replace(hour=6)            # n3 过滤后最新=n2


@pytest.mark.asyncio
async def test_get_authors_reason_exact_username(monkeypatch, tmp_path):
    """reason 精确 username 匹配(复刻旧 ScraperFollow.username.in_(usernames));follow 大小写不同
    →不匹配(故障注入:reason 改 lower 则误匹配返 "大写关注" 翻红)。FileFollowStore 精确 username 保 case。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    day = datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc)
    await _seed_file(tmp_path, [_tweet("e1", "alice", day)], follows=[("Alice", "大写关注")])
    from src.data_layer.provider import get_browse_repo
    authors = await get_browse_repo().get_authors("2026-05-10", tz_offset=0)
    assert len(authors) == 1 and authors[0]["author_username"] == "alice"
    assert authors[0]["reason"] is None   # follow "Alice" ≠ author "alice"(精确匹配,非 lower)


@pytest.mark.asyncio
async def test_get_authors_empty_day(monkeypatch, tmp_path):
    """无推文日返回 [](与 get_daily_stats 空月对称)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [_tweet("z1", "alice", datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc))])
    from src.data_layer.provider import get_browse_repo
    authors = await get_browse_repo().get_authors("2026-05-11", tz_offset=0)  # 11 日无推文
    assert authors == []


@pytest.mark.asyncio
async def test_mcp_get_daily_stats_file_mode(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [
        _tweet("md1", "alice", datetime(2026, 5, 2, 3, 0, tzinfo=timezone.utc)),
        _tweet("md2", "bob", datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc)),
    ])
    from mcp.server.fastmcp import FastMCP
    from src.mcp.tools import browse_tools
    mcp = FastMCP("test"); browse_tools.register(mcp)
    fn = mcp._tool_manager._tools["get_daily_stats"].fn
    data = json.loads(await fn(year=2026, month=5, tz_offset=0))
    assert data["success"] is True
    assert data["data"]["daily_stats"] == [{"date": "2026-05-02", "count": 2}]


@pytest.mark.asyncio
async def test_mcp_get_authors_for_date_file_mode(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    day = datetime(2026, 5, 10, 3, 0, tzinfo=timezone.utc)
    await _seed_file(tmp_path, [
        _tweet("ma1", "alice", day), _tweet("ma2", "bob", day.replace(hour=8)),
    ], follows=[("alice", "AI 研究者")])
    from mcp.server.fastmcp import FastMCP
    from src.mcp.tools import browse_tools
    mcp = FastMCP("test"); browse_tools.register(mcp)
    fn = mcp._tool_manager._tools["get_authors_for_date"].fn
    data = json.loads(await fn(date="2026-05-10", tz_offset=0))
    assert data["success"] is True
    assert data["data"]["count"] == 2
    assert [a["author_username"] for a in data["data"]["authors"]] == ["bob", "alice"]
    alice = next(a for a in data["data"]["authors"] if a["author_username"] == "alice")
    assert alice["reason"] == "AI 研究者"
    assert alice["last_tweet_at"].endswith("+00:00")   # MCP isoformat 出 aware,匹配生产 pg
