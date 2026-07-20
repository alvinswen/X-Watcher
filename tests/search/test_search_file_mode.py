"""search search_tweets 在文件层（file 唯一数据层）下运行。
路径可证:种子只进文件层;跨模式对账:同数据 file vs sqlalchemy 同 (items 除 db_created_at, total)
(search 无聚合 div/cast→SQLite 对 ASCII keyword 有效;distinct created_at 避 tie-break;created_at
按 instant 比 + 钉 file aware;db_created_at file None 单独断言)。"""
from datetime import UTC, datetime, timedelta

import pytest


def _tweet(tid, author, created_at, text="hello world", ref_text=None, media=None):
    from src.scraper.domain.models import Tweet
    return Tweet(tweet_id=tid, text=text, created_at=created_at, author_username=author,
                 author_display_name=f"{author} disp", referenced_tweet_text=ref_text, media=media)


def _summary(tid, summary_text=None, translation_text=None):
    from src.summarization.domain.models import SummaryRecord
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return SummaryRecord(summary_id=f"s-{tid}", tweet_id=tid,
                         summary_text=summary_text if summary_text is not None else f"摘要{tid}",
                         translation_text=translation_text if translation_text is not None else f"译文{tid}",
                         model_provider="p", model_name="m", prompt_tokens=1, completion_tokens=1,
                         total_tokens=2, cost_usd=0.0, content_hash=f"h-{tid}", created_at=now, updated_at=now)


async def _seed_file(tmp_path, tweets, summaries=()):
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
    await FileTweetStore(tmp_path).save_tweets(list(tweets), early_stop_threshold=0)
    if summaries:
        await FileSummaryStore(tmp_path).seed(list(summaries))


@pytest.mark.asyncio
async def test_search_file_mode_multi_keyword_and(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    # s1 含 alpha+beta;s2 仅 alpha;s3 仅 beta
    await _seed_file(tmp_path, [
        _tweet("s1", "alice", base + timedelta(minutes=1), text="alpha beta gamma"),
        _tweet("s2", "alice", base + timedelta(minutes=2), text="alpha only"),
        _tweet("s3", "alice", base + timedelta(minutes=3), text="beta only"),
    ])
    from src.data_layer.provider import get_search_repo

    # 多词 AND:"alpha beta" 只命中 s1(两词都在)
    r = await get_search_repo().search_tweets(q="alpha beta")
    assert r.total == 1 and {i["tweet_id"] for i in r.items} == {"s1"}
    # 单词:"alpha" 命中 s1+s2
    r2 = await get_search_repo().search_tweets(q="alpha")
    assert r2.total == 2 and {i["tweet_id"] for i in r2.items} == {"s1", "s2"}


@pytest.mark.asyncio
async def test_search_file_mode_referenced_text_and_summary(monkeypatch, tmp_path):
    """keyword 命中 referenced_tweet_text(feed 没有的字段)/ summary;include_summary=False 不搜 summary。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    await _seed_file(tmp_path, [
        _tweet("r1", "alice", base + timedelta(minutes=1), text="plain", ref_text="引用里有 zebra"),
        _tweet("r2", "alice", base + timedelta(minutes=2), text="plain too"),
    ], summaries=[_summary("r2", summary_text="摘要含 zebra")])
    from src.data_layer.provider import get_search_repo

    # include_summary=True:zebra 命中 r1(ref_text)+ r2(summary)
    r = await get_search_repo().search_tweets(q="zebra", include_summary=True)
    assert r.total == 2 and {i["tweet_id"] for i in r.items} == {"r1", "r2"}
    # include_summary=False:zebra 只命中 r1(ref_text;不搜 summary)
    r2 = await get_search_repo().search_tweets(q="zebra", include_summary=False)
    assert r2.total == 1 and {i["tweet_id"] for i in r2.items} == {"r1"}
    assert r2.items[0]["summary_text"] is None


@pytest.mark.asyncio
async def test_search_file_mode_14_field_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    await _seed_file(tmp_path, [_tweet("f1", "alice", base + timedelta(minutes=1), text="findme")],
                     summaries=[_summary("f1")])
    from src.data_layer.provider import get_search_repo

    r = await get_search_repo().search_tweets(q="findme")
    item = r.items[0]
    assert set(item) == {"tweet_id","text","author_username","author_display_name","created_at",
        "db_created_at","reference_type","referenced_tweet_id","referenced_tweet_text",
        "referenced_tweet_author_username","media","referenced_tweet_media","summary_text","translation_text"}
    assert item["db_created_at"] is None                     # file 模式
    assert item["created_at"].tzinfo is not None             # aware
    assert item["summary_text"] == "摘要f1"


@pytest.mark.asyncio
async def test_search_file_mode_window_fastpath_and_pagination(monkeypatch, tmp_path):
    """since 提供→窗口快路径;offset 分页(page=2)。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    await _seed_file(tmp_path, [_tweet(f"w{i}", "alice", base + timedelta(minutes=i), text="kw") for i in range(5)])
    from src.data_layer.provider import get_search_repo

    # 窗口快路径(since 提供)+ page_size=2 page=2 → DESC 第 3-4 新(w2,w1)
    r = await get_search_repo().search_tweets(q="kw", since=base - timedelta(hours=1),
                                              until=base + timedelta(hours=1), page=2, page_size=2)
    assert r.total == 5
    assert [i["tweet_id"] for i in r.items] == ["w2", "w1"]   # DESC offset=2


@pytest.mark.asyncio
async def test_search_file_mode_author_and_until_only(monkeypatch, tmp_path):
    """author 过滤 + until-only(since 无)全扫兜底路径。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    await _seed_file(tmp_path, [
        _tweet("a1", "alice", base + timedelta(minutes=1), text="kw"),
        _tweet("a2", "BOB", base + timedelta(minutes=2), text="kw"),
        _tweet("a3", "alice", base + timedelta(hours=10), text="kw"),   # until 之后
    ])
    from src.data_layer.provider import get_search_repo

    # until-only(since 无)→全扫 + 过滤 created_at<until;author=alice
    r = await get_search_repo().search_tweets(q="kw", author="ALICE", until=base + timedelta(hours=1))
    assert r.total == 1 and {i["tweet_id"] for i in r.items} == {"a1"}   # a3 被 until 排除,a2 非 alice


@pytest.mark.asyncio
async def test_search_file_mode_media_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    import json

    from src.scraper.domain.models import Media
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    tw = _tweet("m1", "alice", base + timedelta(minutes=1), text="kw", media=[Media(media_key="k1", type="photo")])
    await _seed_file(tmp_path, [tw])
    from src.data_layer.provider import get_search_repo

    r = await get_search_repo().search_tweets(q="kw")
    m = r.items[0]["media"]
    assert isinstance(m, list) and isinstance(m[0], dict)
    assert "preview_image_url" not in m[0]   # exclude_none
    json.dumps(m)   # plain dict 可 json 序列化(MCP 路径)


@pytest.mark.asyncio
async def test_search_tweet_item_accepts_none_db_created_at():
    """schema 改 Optional 后 SearchTweetItem 接受 file 模式 db_created_at=None。"""
    from datetime import datetime

    from src.search.api.schemas import SearchTweetItem
    item = {"tweet_id": "x", "text": "t", "author_username": "a", "author_display_name": None,
            "created_at": datetime(2024, 1, 1, tzinfo=UTC), "db_created_at": None,
            "reference_type": None, "referenced_tweet_id": None, "referenced_tweet_text": None,
            "referenced_tweet_author_username": None, "media": None, "referenced_tweet_media": None,
            "summary_text": None, "translation_text": None}
    obj = SearchTweetItem(**item)
    assert obj.db_created_at is None


@pytest.mark.asyncio
async def test_mcp_search_tweets_file_mode(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
    base = now - timedelta(days=1)
    await _seed_file(tmp_path, [_tweet("ms1", "alice", base + timedelta(minutes=1), text="needle here"),
                                _tweet("ms2", "alice", base + timedelta(minutes=2), text="other")])
    from mcp.server.fastmcp import FastMCP

    from src.mcp.tools import feed_tools
    mcp = FastMCP("test")
    feed_tools.register(mcp)
    fn = mcp._tool_manager._tools["search_tweets"].fn
    raw = await fn(q="needle")
    data = json.loads(raw)
    assert data["success"] is True
    assert data["data"]["total"] == 1 and data["data"]["count"] == 1
    assert {i["tweet_id"] for i in data["data"]["items"]} == {"ms1"}
    assert all(i["db_created_at"] is None for i in data["data"]["items"])
