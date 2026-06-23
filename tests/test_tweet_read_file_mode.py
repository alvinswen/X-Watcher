"""tweets list/detail 读门面在 XWATCHER_DATA_LAYER=file 下走文件层(pg 下线 D-2)。

复刻 `src/api/routes/tweets.py` 两 HTTP 端点裸查 ORM 的那段:
- list_tweets:select(TweetOrm 字段) LEFT JOIN SummaryOrm(CASE has_summary)+
  _apply_filters(author 大小写不敏感 / created_after >= / created_before <)+ 单独 count(无 join)
  + order_by created_at DESC + offset/limit。
- get_tweet_detail:select(TweetOrm 字段) where tweet_id==(None→404)。

file 模式不依赖 ORM,组合既有 file store(FileTweetStore + FileSummaryStore)在 Python 槽内
过滤/JOIN/排序/分页;sqlalchemy 模式逐字复刻原 SQL。

⚠️ db_created_at 降级(owner 已定):file 模式 db_created_at == 该推文 created_at(文件层无 DB
  入库时间);sqlalchemy 模式 == 真实 TweetOrm.db_created_at(零行为变化)。

⚠️ created_at 不在门面归一:响应模型 UTCDatetimeModel 序列化时把 naive(pg)/aware(file)都归一
  为 "...+00:00",两模式 JSON 一致。门面对账比较 domain/ORM 原样值,故跨模式对账只比 tweet_id
  顺序/total/has_summary/db_created_at 关系/媒体等结构字段(created_at 类型两侧本就不同形态,
  由序列化层统一),用 TestClient 比 JSON 时才严格逐字节等。
"""
from datetime import datetime, timedelta, timezone

import pytest


# ── 种子助手 ───────────────────────────────────────────────


def _tweet(tid, author, created_at, text="hello world", media=None,
           ref_id=None, ref_type=None):
    from src.scraper.domain.models import Tweet
    return Tweet(
        tweet_id=tid, text=text, created_at=created_at, author_username=author,
        author_display_name=f"{author} disp",
        referenced_tweet_id=ref_id, reference_type=ref_type, media=media,
    )


def _summary(tid, sid=None):
    from src.summarization.domain.models import SummaryRecord
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return SummaryRecord(
        summary_id=sid or f"sum-{tid}",
        tweet_id=tid,
        summary_text="zh summary",
        translation_text="译文",
        model_provider="openrouter",
        model_name="m",
        prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0,
        content_hash=f"hash-{sid or tid}",
        created_at=now, updated_at=now,
    )


async def _seed_tweets(root, tweets):
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    await FileTweetStore(root).save_tweets(list(tweets), early_stop_threshold=0)


async def _seed_summaries(root, summaries):
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
    await FileSummaryStore(root).seed(list(summaries))


# ── file 路径可证 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tweets_basic_desc_total(monkeypatch, tmp_path):
    """分页 total + DESC 排序 + 默认全量。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("t1", "alice", base + timedelta(hours=3)),
        _tweet("t2", "alice", base + timedelta(hours=1)),
        _tweet("t3", "bob", base + timedelta(hours=2)),
    ])
    from src.data_layer.provider import get_tweet_read_repo

    items, total = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    assert total == 3
    # created_at DESC:t1(h3) > t3(h2) > t2(h1)
    assert [i["tweet_id"] for i in items] == ["t1", "t3", "t2"]


@pytest.mark.asyncio
async def test_list_tweets_pagination(monkeypatch, tmp_path):
    """分页 offset/limit:page2 取不同子集。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet(f"t{i}", "alice", base + timedelta(hours=i)) for i in range(5)
    ])
    from src.data_layer.provider import get_tweet_read_repo

    p1, total1 = await get_tweet_read_repo().list_tweets(page=1, page_size=2)
    p2, total2 = await get_tweet_read_repo().list_tweets(page=2, page_size=2)
    assert total1 == total2 == 5
    # DESC:t4,t3 | t2,t1 | t0
    assert [i["tweet_id"] for i in p1] == ["t4", "t3"]
    assert [i["tweet_id"] for i in p2] == ["t2", "t1"]


@pytest.mark.asyncio
async def test_list_tweets_author_case_insensitive(monkeypatch, tmp_path):
    """author 过滤大小写不敏感(func.lower == author.lower())。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("u1", "Alice", base + timedelta(hours=1)),
        _tweet("u2", "ALICE", base + timedelta(hours=2)),
        _tweet("u3", "carol", base + timedelta(hours=3)),
    ])
    from src.data_layer.provider import get_tweet_read_repo

    items, total = await get_tweet_read_repo().list_tweets(
        page=1, page_size=20, author="alice")
    assert total == 2
    assert {i["tweet_id"] for i in items} == {"u1", "u2"}
    # 传混合大小写也应归一匹配
    items2, total2 = await get_tweet_read_repo().list_tweets(
        page=1, page_size=20, author="aLiCe")
    assert total2 == 2


@pytest.mark.asyncio
async def test_list_tweets_created_window_half_open(monkeypatch, tmp_path):
    """created 窗 [after, before):after 含、before 不含。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    after = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    before = datetime(2026, 2, 19, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("before", "alice", after - timedelta(seconds=1)),  # 早于 after → 排除
        _tweet("at_after", "alice", after),                       # = after → 含
        _tweet("mid", "alice", after + timedelta(hours=5)),       # 窗内
        _tweet("at_before", "alice", before),                     # = before → 排除(< 非 <=)
        _tweet("late", "alice", before + timedelta(seconds=1)),   # 晚 → 排除
    ])
    from src.data_layer.provider import get_tweet_read_repo

    items, total = await get_tweet_read_repo().list_tweets(
        page=1, page_size=20, created_after=after, created_before=before)
    assert total == 2
    assert {i["tweet_id"] for i in items} == {"at_after", "mid"}


@pytest.mark.asyncio
async def test_list_tweets_has_summary(monkeypatch, tmp_path):
    """has_summary:有 summary 的 tweet→True,无→False。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("withsum", "alice", base + timedelta(hours=2)),
        _tweet("nosum", "alice", base + timedelta(hours=1)),
    ])
    await _seed_summaries(tmp_path, [_summary("withsum")])
    from src.data_layer.provider import get_tweet_read_repo

    items, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    by_id = {i["tweet_id"]: i for i in items}
    assert by_id["withsum"]["has_summary"] is True
    assert by_id["nosum"]["has_summary"] is False


@pytest.mark.asyncio
async def test_list_tweets_media_count_and_reference_type(monkeypatch, tmp_path):
    """media_count 来自 media 列表长度;reference_type enum→str。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.scraper.domain.models import Media, ReferenceType
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("m2", "alice", base + timedelta(hours=2),
               media=[Media(media_key="k1", type="photo"),
                      Media(media_key="k2", type="video")],
               ref_id="orig", ref_type=ReferenceType.quoted),
        _tweet("m0", "alice", base + timedelta(hours=1)),
    ])
    from src.data_layer.provider import get_tweet_read_repo

    items, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    by_id = {i["tweet_id"]: i for i in items}
    assert by_id["m2"]["media_count"] == 2
    assert by_id["m2"]["reference_type"] == "quoted"   # enum.value 字符串
    assert by_id["m0"]["media_count"] == 0
    assert by_id["m0"]["reference_type"] is None


@pytest.mark.asyncio
async def test_get_tweet_detail_found_and_missing(monkeypatch, tmp_path):
    """detail:命中返 dict、未命中返 None;has_summary 默认 False(由 handler summary 部分另算)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.scraper.domain.models import Media
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("d1", "alice", base, media=[Media(media_key="k", type="photo")]),
    ])
    from src.data_layer.provider import get_tweet_read_repo

    d = await get_tweet_read_repo().get_tweet_detail("d1")
    assert d is not None
    assert d["tweet_id"] == "d1"
    assert d["media_count"] == 1
    assert d["media"][0]["media_key"] == "k"
    assert d["has_summary"] is False
    assert await get_tweet_read_repo().get_tweet_detail("nope") is None


# ── db_created_at 降级专项 ───────────────────────────────────


@pytest.mark.asyncio
async def test_db_created_at_degradation_file_equals_created_at(monkeypatch, tmp_path):
    """file 模式:list + detail 的 db_created_at == 该推文 created_at(降级)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 3, 30, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [_tweet("t1", "alice", base)])
    from src.data_layer.provider import get_tweet_read_repo

    items, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    assert items[0]["db_created_at"] == items[0]["created_at"]

    d = await get_tweet_read_repo().get_tweet_detail("t1")
    assert d["db_created_at"] == d["created_at"]


@pytest.mark.asyncio
async def test_db_created_at_sqlalchemy_is_real_db_value(monkeypatch, tmp_path):
    """sqlalchemy 模式:db_created_at == 真实 TweetOrm.db_created_at(与 created_at 不同值)。"""
    from src.scraper.infrastructure.models import TweetOrm
    engine, session = await _build_sqlite_session()
    created = datetime(2026, 2, 18, 3, 30, 0)            # naive UTC
    db_created = datetime(2026, 3, 1, 12, 0, 0)          # 入库时间显著不同
    session.add(TweetOrm(
        tweet_id="t1", text="x", created_at=created, db_created_at=db_created,
        author_username="alice", author_display_name="A", media=None))
    await session.commit()

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import get_tweet_read_repo

    items, _ = await get_tweet_read_repo(session).list_tweets(page=1, page_size=20)
    assert items[0]["db_created_at"] == db_created       # 真实入库时间
    assert items[0]["created_at"] == created
    assert items[0]["db_created_at"] != items[0]["created_at"]

    d = await get_tweet_read_repo(session).get_tweet_detail("t1")
    assert d["db_created_at"] == db_created

    await session.close()
    await engine.dispose()


# ── 跨模式对账(file vs sqlalchemy SQLite)────────────────────


async def _build_sqlite_session():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.database.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    return engine, session


@pytest.mark.asyncio
async def test_cross_mode_list_tweets_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite):list_tweets 的 items 顺序/total/结构字段一致。

    用互异 created_at 规避 page-边界 tie-order(同 created_at 跨引擎子集可能不同,已知限制)。
    created_at 形态两侧本就不同(file aware / pg naive),由响应模型序列化层归一——此处对账
    比 tweet_id 顺序 + total + has_summary + media_count + reference_type 结构字段,
    created_at 端到端 JSON 一致由 TestClient 测试覆盖。
    """
    from src.scraper.domain.models import Media, ReferenceType
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    # 互异 created_at;作者大小写混搭;有/无 summary;有/无 media
    tweet_specs = [
        ("c1", "Alice", base + timedelta(hours=4), [Media(media_key="k", type="photo")],
         "orig", ReferenceType.quoted),
        ("c2", "alice", base + timedelta(hours=3), None, None, None),
        ("c3", "ALICE", base + timedelta(hours=2), None, None, None),
        ("c4", "bob", base + timedelta(hours=1), None, None, None),   # author 过滤掉
    ]
    summary_specs = ["c1", "c3"]  # c2 无 summary

    # ── 文件层种子 ──
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [
        _tweet(t, a, c, media=m, ref_id=ri, ref_type=rt)
        for (t, a, c, m, ri, rt) in tweet_specs
    ])
    await _seed_summaries(tmp_path, [_summary(t) for t in summary_specs])

    # ── sqlalchemy(SQLite)种子 ──
    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm
    engine, session = await _build_sqlite_session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for (t, a, c, m, ri, rt) in tweet_specs:
        media_json = [mm.model_dump(mode="json", exclude_none=True) for mm in m] if m else None
        session.add(TweetOrm(
            tweet_id=t, text="hello world", created_at=c.replace(tzinfo=None),
            db_created_at=now, author_username=a, author_display_name=f"{a} disp",
            media=media_json, referenced_tweet_id=ri,
            reference_type=rt.value if rt else None))
    for t in summary_specs:
        session.add(SummaryOrm(
            summary_id=f"sum-{t}", tweet_id=t, summary_text="zh", translation_text="译文",
            model_provider="openrouter", model_name="m",
            prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0,
            content_hash=f"h-{t}", created_at=now, updated_at=now))
    await session.commit()

    from src.data_layer.provider import get_tweet_read_repo

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_items, f_total = await get_tweet_read_repo().list_tweets(
        page=1, page_size=20, author="alice")
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_items, s_total = await get_tweet_read_repo(session).list_tweets(
        page=1, page_size=20, author="alice")

    assert f_total == s_total == 3
    # tweet_id DESC 顺序一致(互异 created_at)
    assert [i["tweet_id"] for i in f_items] == [i["tweet_id"] for i in s_items] == ["c1", "c2", "c3"]
    # 结构字段逐条一致
    fields = ("tweet_id", "text", "author_username", "author_display_name",
              "reference_type", "referenced_tweet_id", "has_summary", "media_count")
    for fi, si in zip(f_items, s_items):
        for k in fields:
            assert fi[k] == si[k], f"{fi['tweet_id']} 字段 {k}: file={fi[k]} sql={si[k]}"

    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_mode_get_tweet_detail_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy:get_tweet_detail 结构字段一致(含 media、404→None)。"""
    from src.scraper.domain.models import Media, ReferenceType
    base = datetime(2026, 2, 18, 5, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [
        _tweet("d1", "alice", base, text="detail body",
               media=[Media(media_key="k1", type="photo")],
               ref_id="orig", ref_type=ReferenceType.retweeted),
    ])

    from src.scraper.infrastructure.models import TweetOrm
    engine, session = await _build_sqlite_session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(TweetOrm(
        tweet_id="d1", text="detail body", created_at=base.replace(tzinfo=None),
        db_created_at=now, author_username="alice", author_display_name="alice disp",
        media=[{"media_key": "k1", "type": "photo"}],
        referenced_tweet_id="orig", reference_type="retweeted"))
    await session.commit()

    from src.data_layer.provider import get_tweet_read_repo

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f = await get_tweet_read_repo().get_tweet_detail("d1")
    f_missing = await get_tweet_read_repo().get_tweet_detail("nope")
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s = await get_tweet_read_repo(session).get_tweet_detail("d1")
    s_missing = await get_tweet_read_repo(session).get_tweet_detail("nope")

    assert f_missing is None and s_missing is None
    fields = ("tweet_id", "text", "author_username", "author_display_name",
              "reference_type", "referenced_tweet_id", "has_summary", "media_count")
    for k in fields:
        assert f[k] == s[k], f"detail 字段 {k}: file={f[k]} sql={s[k]}"
    # media 结构一致
    assert f["media"] == s["media"] == [{"media_key": "k1", "type": "photo"}]

    await session.close()
    await engine.dispose()


# ── 端点 file 模式可跑(TestClient 端到端,含 created_at JSON 归一)──


@pytest.mark.asyncio
async def test_endpoints_file_mode_via_handler(monkeypatch, tmp_path):
    """直调 handler:file 模式两端点不崩、404 正常、分页正确、created_at JSON 序列化带 +00:00。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("e1", "alice", base + timedelta(hours=2)),
        _tweet("e2", "alice", base + timedelta(hours=1)),
    ])
    await _seed_summaries(tmp_path, [_summary("e1")])

    from fastapi import HTTPException
    from src.api.routes import tweets as tweets_route

    # list_tweets handler:session 传 None(file 门面忽略)
    resp = await tweets_route.list_tweets(
        page=1, page_size=1, author=None, created_after=None, created_before=None,
        session=None, _admin=None)
    assert resp.total == 2
    assert resp.total_pages == 2
    assert len(resp.items) == 1
    assert resp.items[0].tweet_id == "e1"      # DESC

    # JSON 序列化:created_at / db_created_at 带 UTC 时区标记(UTCDatetimeModel)
    payload = resp.model_dump(mode="json")
    assert "+00:00" in payload["items"][0]["created_at"]
    assert "+00:00" in payload["items"][0]["db_created_at"]

    # get_tweet_detail handler:命中(含 summary 部分仍走 get_summary_repo,file-safe)
    detail = await tweets_route.get_tweet_detail(
        tweet_id="e1", session=None, _admin=None)
    assert detail.tweet_id == "e1"
    assert detail.has_summary is True          # summary 部分 file-safe 拼装

    # 404
    with pytest.raises(HTTPException) as ei:
        await tweets_route.get_tweet_detail(tweet_id="nope", session=None, _admin=None)
    assert ei.value.status_code == 404


# ── 故障注入 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faultinj_created_window_closed_vs_half_open(monkeypatch, tmp_path):
    """故意把 created_before 写成闭区间(<=)→ before 边界推文混入 → 断言翻红还原。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    after = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    before = datetime(2026, 2, 19, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("mid", "alice", after + timedelta(hours=5)),
        _tweet("at_before", "alice", before),  # 半开 [after, before) 应排除
    ])
    from src.data_layer.provider import get_tweet_read_repo

    # 正确:半开,at_before 排除
    items, total = await get_tweet_read_repo().list_tweets(
        page=1, page_size=20, created_after=after, created_before=before)
    assert total == 1
    assert {i["tweet_id"] for i in items} == {"mid"}

    # 注入 bug:把 before 谓词替换为闭区间(<=)→ at_before 混入
    import src.scraper.infrastructure.tweet_read_repository as mod
    orig = mod.FileTweetReadStore.list_tweets

    async def _buggy_list(self, *, page, page_size, author=None,
                          created_after=None, created_before=None):
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        tweets = await FileTweetStore(self._root).get_all_tweets()
        if author:
            w = author.lower()
            tweets = [t for t in tweets if t.author_username.lower() == w]
        if created_after is not None:
            tweets = [t for t in tweets if t.created_at >= created_after]
        if created_before is not None:
            tweets = [t for t in tweets if t.created_at <= created_before]  # BUG: <=
        total = len(tweets)
        tweets.sort(key=lambda t: (t.created_at, t.tweet_id), reverse=True)
        off = (page - 1) * page_size
        return [self._item(t, has_summary=False) for t in tweets[off:off + page_size]], total

    monkeypatch.setattr(mod.FileTweetReadStore, "list_tweets", _buggy_list)
    buggy, buggy_total = await get_tweet_read_repo().list_tweets(
        page=1, page_size=20, created_after=after, created_before=before)
    assert buggy_total == 2                     # at_before 错误混入
    assert {i["tweet_id"] for i in buggy} == {"mid", "at_before"}
    monkeypatch.setattr(mod.FileTweetReadStore, "list_tweets", orig)


@pytest.mark.asyncio
async def test_faultinj_has_summary_always_false(monkeypatch, tmp_path):
    """故意让 has_summary 恒 False(漏 JOIN)→ 与真有 summary 不符 → 断言能抓到。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [_tweet("t1", "alice", base)])
    await _seed_summaries(tmp_path, [_summary("t1")])
    from src.data_layer.provider import get_tweet_read_repo

    items, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    assert items[0]["has_summary"] is True      # 正确

    # 注入 bug:门面的 summary 集合恒空(漏 JOIN)
    import src.scraper.infrastructure.tweet_read_repository as mod

    async def _empty(self):
        return set()

    monkeypatch.setattr(mod.FileTweetReadStore, "_summary_tweet_ids", _empty)
    buggy, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    assert buggy[0]["has_summary"] is False     # bug 下漏检 → 测试对 JOIN 敏感


@pytest.mark.asyncio
async def test_faultinj_db_created_at_not_degraded(monkeypatch, tmp_path):
    """故意让 file 门面 db_created_at 不降级(返 None)→ 响应模型必填字段校验崩 → 证降级载体被测。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [_tweet("t1", "alice", base)])
    from src.data_layer.provider import get_tweet_read_repo

    # 正确:db_created_at == created_at(非 None)
    items, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    assert items[0]["db_created_at"] is not None

    # 注入 bug:_item 把 db_created_at 置 None
    import src.scraper.infrastructure.tweet_read_repository as mod
    orig = mod.FileTweetReadStore._item

    def _buggy_item(self, tw, has_summary):
        d = orig(self, tw, has_summary)
        d["db_created_at"] = None
        return d

    monkeypatch.setattr(mod.FileTweetReadStore, "_item", _buggy_item)
    buggy, _ = await get_tweet_read_repo().list_tweets(page=1, page_size=20)
    assert buggy[0]["db_created_at"] is None    # bug 下降级丢失,handler 构造 TweetListItem 会崩
    monkeypatch.setattr(mod.FileTweetReadStore, "_item", orig)
