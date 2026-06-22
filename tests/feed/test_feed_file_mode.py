"""feed get_feed 在 XWATCHER_DATA_LAYER=file 下走文件层。
路径可证:种子只进文件层;跨模式对账:同数据 file vs sqlalchemy 同 (items 除 db_created_at,
count,total,has_more)(feed 无聚合 div/cast→SQLite 对 ASCII keyword 是有效 oracle;seed distinct
created_at 避 tie-break;created_at 按 instant 比 + 单独钉 file aware;db_created_at file None 单独断言)。"""
from datetime import datetime, timedelta, timezone

import pytest


def _tweet(tid, author, created_at, text="hello world", media=None):
    from src.scraper.domain.models import Tweet
    return Tweet(tweet_id=tid, text=text, created_at=created_at, author_username=author,
                 author_display_name=f"{author} disp", media=media)


def _summary(tid, summary_text=None, translation_text=None):
    from src.summarization.domain.models import SummaryRecord
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
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
async def test_get_feed_file_mode_window_join_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    since = base - timedelta(hours=1)
    until = base + timedelta(hours=1)
    # 3 条窗口内 distinct created_at;t2 有 summary;t_out 在窗口外
    await _seed_file(tmp_path, [
        _tweet("t1", "alice", base + timedelta(minutes=1)),
        _tweet("t2", "alice", base + timedelta(minutes=2)),
        _tweet("t3", "bob", base + timedelta(minutes=3)),
        _tweet("t_out", "alice", base + timedelta(hours=5)),   # 窗口外
    ], summaries=[_summary("t2")])
    from src.data_layer.provider import get_feed_repo

    result = await get_feed_repo().get_feed(since=since, until=until, limit=10)
    assert result.total == 3
    assert [i["tweet_id"] for i in result.items] == ["t3", "t2", "t1"]   # DESC
    by_id = {i["tweet_id"]: i for i in result.items}
    assert by_id["t2"]["summary_text"] == "摘要t2" and by_id["t2"]["translation_text"] == "译文t2"
    assert by_id["t1"]["summary_text"] is None    # LEFT JOIN 未命中
    # 11 键齐全(feed 形态:有 db_created_at,无 referenced_tweet_text/author/media)
    assert set(by_id["t1"]) == {"tweet_id","text","author_username","author_display_name","created_at",
        "db_created_at","reference_type","referenced_tweet_id","media","summary_text","translation_text"}
    # db_created_at file 模式 None;created_at aware
    assert all(i["db_created_at"] is None for i in result.items)
    assert all(i["created_at"].tzinfo is not None for i in result.items)


@pytest.mark.asyncio
async def test_get_feed_file_mode_limit_cursor(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    await _seed_file(tmp_path, [_tweet(f"c{i}", "alice", base + timedelta(minutes=i)) for i in range(5)])
    from src.data_layer.provider import get_feed_repo

    result = await get_feed_repo().get_feed(since=base - timedelta(hours=1),
                                            until=base + timedelta(hours=1), limit=2)
    assert result.total == 5 and result.count == 2 and result.has_more is True
    assert [i["tweet_id"] for i in result.items] == ["c4", "c3"]   # DESC top-2


@pytest.mark.asyncio
async def test_get_feed_file_mode_author_filter(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    win = dict(since=base - timedelta(hours=1), until=base + timedelta(hours=1), limit=10)
    await _seed_file(tmp_path, [
        _tweet("p1", "alice", base + timedelta(minutes=1)),
        _tweet("p2", "BOB", base + timedelta(minutes=2)),
        _tweet("p3", "carol", base + timedelta(minutes=3)),
    ])
    from src.data_layer.provider import get_feed_repo

    # 单 author 大小写不敏感
    r1 = await get_feed_repo().get_feed(author="ALICE", **win)
    assert {i["tweet_id"] for i in r1.items} == {"p1"} and r1.total == 1
    # authors 多作者大小写不敏感
    r2 = await get_feed_repo().get_feed(authors=["bob", "Carol"], **win)
    assert {i["tweet_id"] for i in r2.items} == {"p2", "p3"} and r2.total == 2


@pytest.mark.asyncio
async def test_get_feed_file_mode_keyword(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    win = dict(since=base - timedelta(hours=1), until=base + timedelta(hours=1), limit=10)
    # k1 text 含 GPT;k2 text 无但 summary 含;k3 text 无 summary 无
    await _seed_file(tmp_path, [
        _tweet("k1", "alice", base + timedelta(minutes=1), text="new GPT model"),
        _tweet("k2", "alice", base + timedelta(minutes=2), text="unrelated tweet"),
        _tweet("k3", "alice", base + timedelta(minutes=3), text="nothing here"),
    ], summaries=[_summary("k2", summary_text="关于 gpt 的摘要")])
    from src.data_layer.provider import get_feed_repo

    # include_summary=True:大小写不敏感 + OR 搜 summary → k1(text)+k2(summary)
    r_inc = await get_feed_repo().get_feed(keyword="gpt", include_summary=True, **win)
    assert {i["tweet_id"] for i in r_inc.items} == {"k1", "k2"} and r_inc.total == 2
    # include_summary=False:仅搜 text → 只 k1
    r_exc = await get_feed_repo().get_feed(keyword="gpt", include_summary=False, **win)
    assert {i["tweet_id"] for i in r_exc.items} == {"k1"} and r_exc.total == 1
    assert r_exc.items[0]["summary_text"] is None   # include_summary=False → summary None


@pytest.mark.asyncio
async def test_get_feed_file_mode_keyword_like_wildcard(monkeypatch, tmp_path):
    """keyword 内 `_` 复刻 SQL LIKE 通配(任意单字符),非 naive substring。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    win = dict(since=base - timedelta(hours=1), until=base + timedelta(hours=1), limit=10)
    await _seed_file(tmp_path, [
        _tweet("w1", "alice", base + timedelta(minutes=1), text="abc here"),   # a_c 匹配 abc
        _tweet("w2", "alice", base + timedelta(minutes=2), text="axc here"),   # a_c 匹配 axc
        _tweet("w3", "alice", base + timedelta(minutes=3), text="ac here"),    # a_c 不匹配(_ 须 1 字符)
    ], summaries=())
    from src.data_layer.provider import get_feed_repo

    # keyword "a_c":LIKE `_`=任意单字符 → w1(abc)+w2(axc),非 w3(ac);naive `in` 会全不中
    r = await get_feed_repo().get_feed(keyword="a_c", include_summary=False, **win)
    assert {i["tweet_id"] for i in r.items} == {"w1", "w2"} and r.total == 2


@pytest.mark.asyncio
async def test_get_feed_file_mode_media_shape(monkeypatch, tmp_path):
    """media 存在时 file 模式产 list[dict] exclude_none(json 可序列化,MCP 路径必需)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    import json
    from src.scraper.domain.models import Media
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    tw = _tweet("m1", "alice", base + timedelta(minutes=1), media=[Media(media_key="k1", type="photo")])
    await _seed_file(tmp_path, [tw])
    from src.data_layer.provider import get_feed_repo

    result = await get_feed_repo().get_feed(since=base - timedelta(hours=1),
                                            until=base + timedelta(hours=1), limit=10)
    m = result.items[0]["media"]
    assert isinstance(m, list) and isinstance(m[0], dict)
    assert "preview_image_url" not in m[0]   # exclude_none:None 键省略(匹配生产 pg)
    json.dumps(m)   # media 是 plain dict(全字符串)可 json 序列化;若为 Media 对象会抛(MCP 路径必需)


@pytest.mark.asyncio
async def test_feed_tweet_item_accepts_none_db_created_at():
    """schema 改 Optional 后 FeedTweetItem 接受 file 模式 db_created_at=None。"""
    from datetime import datetime, timezone
    from src.feed.api.schemas import FeedTweetItem
    item = {"tweet_id": "x", "text": "t", "author_username": "a", "author_display_name": None,
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "db_created_at": None,
            "reference_type": None, "referenced_tweet_id": None, "media": None,
            "summary_text": None, "translation_text": None}
    obj = FeedTweetItem(**item)
    assert obj.db_created_at is None


@pytest.mark.asyncio
async def test_cross_mode_feed_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite)产同 (items 除 db_created_at, count, total, has_more)。
    ASCII keyword;distinct created_at 避 tie-break;created_at 按 instant 比 + 单独钉 file aware;
    db_created_at file None / sqlalchemy 非 None 单独断言。"""
    now = datetime.now(timezone.utc)
    base = now - timedelta(days=1)
    since = base - timedelta(hours=1)
    until = base + timedelta(hours=1)
    tw_specs = [("t1", "alice", base + timedelta(minutes=1), "alpha GPT"),
                ("t2", "alice", base + timedelta(minutes=2), "beta text"),
                ("t3", "bob", base + timedelta(minutes=3), "gamma gpt here")]
    sum_tids = ["t2"]
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [_tweet(t, a, c, text=x) for (t, a, c, x) in tw_specs],
                     summaries=[_summary(t) for t in sum_tids])

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.database.models import Base
    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    for (t, a, c, x) in tw_specs:
        session.add(TweetOrm(tweet_id=t, text=x, created_at=c, db_created_at=now,
                             author_username=a, author_display_name=f"{a} disp", media=None))
    for t in sum_tids:
        session.add(SummaryOrm(summary_id=f"s-{t}", tweet_id=t, summary_text=f"摘要{t}",
                               translation_text=f"译文{t}", content_hash=f"h-{t}", model_provider="p",
                               model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0))
    await session.commit()

    from src.data_layer.provider import get_feed_repo

    def _norm(items):
        out = []
        for it in items:
            d = dict(it)
            d.pop("db_created_at", None)   # file None vs sqlalchemy 真值,合法分歧,剥离
            ca = d["created_at"]
            if ca is not None and ca.tzinfo is not None:
                d["created_at"] = ca.astimezone(timezone.utc).replace(tzinfo=None)
            out.append(d)
        return out

    cases = [dict(since=since, until=until, limit=10),
             dict(since=since, until=until, limit=10, keyword="gpt"),
             dict(since=since, until=until, limit=10, author="alice")]
    for kw in cases:
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        f = await get_feed_repo().get_feed(**kw)
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
        s = await get_feed_repo(session).get_feed(**kw)
        assert f.total == s.total and f.count == s.count and f.has_more == s.has_more, f"meta 不等 {kw}"
        assert _norm(f.items) == _norm(s.items), f"items 不等 {kw}\nfile={f.items}\nsql={s.items}"
        # file 钉生产语义 + db_created_at 双面
        assert all(i["created_at"].tzinfo is not None for i in f.items)
        assert all(i["db_created_at"] is None for i in f.items)
        assert all(i["db_created_at"] is not None for i in s.items)

    await session.close(); await engine.dispose()
