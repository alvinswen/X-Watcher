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
    # MCP 路径经 success_response 的 json.dumps(default=_default_serializer);datetime→isoformat
    # 兜底,其余必须已是 plain JSON 类型(media→dict)。逐字复刻该契约,而非裸 json.dumps。
    from src.mcp.helpers import _default_serializer
    json.dumps(items, default=_default_serializer)


@pytest.mark.asyncio
async def test_cross_mode_browse_equivalence(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    base = now.replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
    date_str = base.strftime("%Y-%m-%d")
    tw_specs = [("t1","alice",base+timedelta(minutes=1)), ("t2","alice",base+timedelta(minutes=2)),
                ("t3","bob",base+timedelta(minutes=3))]
    sum_tids = ["t2"]
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_file(tmp_path, [_tweet(t,a,c) for (t,a,c) in tw_specs],
                     summaries=[_summary(t) for t in sum_tids], follows=[("alice","r")])

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.database.models import Base, ScraperFollow
    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    session.add(ScraperFollow(username="alice", reason="r", added_by="admin", is_active=True))
    for (t,a,c) in tw_specs:
        session.add(TweetOrm(tweet_id=t, text="hello world", created_at=c, db_created_at=now,
                             author_username=a, author_display_name=f"{a} disp", media=None))
    for t in sum_tids:
        session.add(SummaryOrm(summary_id=f"s-{t}", tweet_id=t, summary_text=f"摘要{t}",
                               translation_text=f"译文{t}", content_hash=f"h-{t}", model_provider="p",
                               model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0))
    await session.commit()

    from src.data_layer.provider import get_browse_repo
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_items, f_total = await get_browse_repo().get_tweets(date_str, None, 1, 20, 0)
    f_meta, f_ti, f_tt = await get_browse_repo().get_author_timeline("alice", base, base+timedelta(days=1), 1, 20)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_items, s_total = await get_browse_repo(session).get_tweets(date_str, None, 1, 20, 0)
    s_meta, s_ti, s_tt = await get_browse_repo(session).get_author_timeline("alice", base, base+timedelta(days=1), 1, 20)
    await session.close(); await engine.dispose()

    assert f_total == s_total == 3
    assert f_items == s_items, f"get_tweets 不等\nfile={f_items}\nsql={s_items}"
    assert (f_meta, f_tt) == (s_meta, s_tt) and f_ti == s_ti
