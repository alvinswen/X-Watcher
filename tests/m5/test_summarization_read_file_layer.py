"""M-5 后续片 summarization 读门面接线集成测试(file vs sqlalchemy 两路径)。

两条读路径各做 file-vs-sqlalchemy 对比 + 默认模式零变化实证:

- get_unsummarized_tweets(反连接):**控制数据集** —— 真实 pg/data_migrated 中所有推文都有摘要
  (反连接恒空,empty-vs-empty 是假绿),故 seed 一份小且互不相同 created_at 的数据集到
  temp 文件层 + temp sqlite session,两侧同输入比对(承"绕脚本独立数源防假绿"教训)。
- get_tweet_origins(原文回查):**真实数据 apples-to-apples** —— 从 data_migrated 抽样真实
  tweet_id,file 侧读 data_migrated、sqlalchemy 侧读真实 pg,这些 tweet_id 两源重叠,
  对比 dict 一致(真实抽样而非固定计数硬断言)。
- Step5 零变化:对同一 seed 数据,适配器产的 dict 经 success_response 序列化 == 原 76ca702
  内联 raw 查询逻辑产的 dict 经 success_response 序列化(逐字),实证默认模式工具 JSON 不变。
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.mcp.helpers import success_response
from src.scraper.domain.models import ReferenceType, Tweet
from src.summarization.domain.models import SummaryRecord


# ---- helpers --------------------------------------------------------------

def _tweet(tid, author="alice", created=datetime(2050, 1, 1), text=None, **kw):
    base = dict(
        tweet_id=tid,
        text=text if text is not None else "t" + tid,
        created_at=created,
        author_username=author,
    )
    base.update(kw)
    return Tweet(**base)


def _summary(sid, tid):
    return SummaryRecord(
        summary_id=sid, tweet_id=tid, summary_text="s", translation_text=None,
        model_provider="p", model_name="m", prompt_tokens=1, completion_tokens=1,
        total_tokens=2, cost_usd=0.0, cached=False, is_generated_summary=True,
        content_hash="h" + sid,
        created_at=datetime(2050, 1, 1), updated_at=datetime(2050, 1, 1),
    )


async def _make_sqlite_sa_store(tmp_path):
    """temp sqlite AsyncSession + SqlalchemySummarizationReadStore,共享 TweetOrm/SummaryOrm 元数据。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.database.models import Base
    from src.scraper.infrastructure.models import TweetOrm  # noqa: F401 (注册元数据)
    from src.summarization.infrastructure.models import SummaryOrm  # noqa: F401
    from src.data_layer._summarization_read_sqlalchemy import SqlalchemySummarizationReadStore

    db = Path(tmp_path) / "sa_read.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    store = SqlalchemySummarizationReadStore(session)

    async def cleanup():
        await session.close()
        await engine.dispose()

    return store, session, cleanup


async def _sa_seed_tweets(session, tweets):
    from src.scraper.infrastructure.models import TweetOrm

    for t in tweets:
        session.add(TweetOrm(
            tweet_id=t.tweet_id, text=t.text, created_at=t.created_at,
            author_username=t.author_username, author_display_name=t.author_display_name,
            author_user_id=t.author_user_id, referenced_tweet_id=t.referenced_tweet_id,
            reference_type=t.reference_type.value if t.reference_type else None,
            referenced_tweet_text=t.referenced_tweet_text,
            referenced_tweet_author_username=t.referenced_tweet_author_username,
        ))
    await session.commit()


async def _sa_seed_summaries(session, records):
    from src.summarization.infrastructure.models import SummaryOrm

    for s in records:
        session.add(SummaryOrm(
            summary_id=s.summary_id, tweet_id=s.tweet_id, summary_text=s.summary_text,
            translation_text=s.translation_text, model_provider=s.model_provider,
            model_name=s.model_name, prompt_tokens=s.prompt_tokens,
            completion_tokens=s.completion_tokens, total_tokens=s.total_tokens,
            cost_usd=s.cost_usd, cached=s.cached,
            is_generated_summary=s.is_generated_summary, content_hash=s.content_hash,
            created_at=s.created_at,
        ))
    await session.commit()


# ---- read path ① get_unsummarized_tweets: file vs sqlalchemy (controlled) -

@pytest.mark.asyncio
async def test_unsummarized_file_vs_sqlalchemy_controlled(monkeypatch, tmp_path):
    """同一 seed 数据,file 与 sqlalchemy 两实现的反连接结果逐字一致(8 字段 + DESC + limit + 过滤)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))
    from src.data_layer.provider import get_summarization_read_repo

    # 互不相同 created_at 规避 tie-break;tweet "2" 已摘要应被反连接排除。
    tweets = [
        _tweet("1", "alice", created=datetime(2050, 1, 1, tzinfo=timezone.utc), text="a1"),
        _tweet("2", "alice", created=datetime(2050, 5, 1, tzinfo=timezone.utc), text="a2"),
        _tweet("3", "alice", created=datetime(2050, 3, 1, tzinfo=timezone.utc), text="a3",
               reference_type=ReferenceType.quoted, referenced_tweet_text="orig",
               referenced_tweet_author_username="orig_a", author_display_name="Alice"),
        _tweet("4", "bob", created=datetime(2050, 2, 1, tzinfo=timezone.utc), text="b4"),
    ]
    summaries = [_summary("s2", "2")]

    # file 侧
    file_store = get_summarization_read_repo()
    await file_store.seed_tweets(tweets)
    await file_store.seed_summaries(summaries)

    # sqlalchemy 侧(temp sqlite)
    sa_store, session, cleanup = await _make_sqlite_sa_store(tmp_path)
    try:
        await _sa_seed_tweets(session, tweets)
        await _sa_seed_summaries(session, summaries)

        # 无过滤:反连接去掉 tweet 2,DESC → [3(3月),4(2月),1(1月)]
        f = await file_store.get_unsummarized_tweets()
        s = await sa_store.get_unsummarized_tweets()
        assert [t["tweet_id"] for t in f] == ["3", "4", "1"]
        assert f == s  # 8 字段逐字一致

        # author 精确匹配(大小写敏感)+ since 半开 [since,) + until 半开 [,until)
        f2 = await file_store.get_unsummarized_tweets(author="alice")
        s2 = await sa_store.get_unsummarized_tweets(author="alice")
        assert [t["tweet_id"] for t in f2] == ["3", "1"]
        assert f2 == s2

        f3 = await file_store.get_unsummarized_tweets(since=datetime(2050, 3, 1, tzinfo=timezone.utc))
        s3 = await sa_store.get_unsummarized_tweets(since=datetime(2050, 3, 1, tzinfo=timezone.utc))
        assert {t["tweet_id"] for t in f3} == {"3"}  # tweet3 恰在端点应纳入;tweet4(2月)排除
        assert f3 == s3

        f4 = await file_store.get_unsummarized_tweets(until=datetime(2050, 3, 1, tzinfo=timezone.utc))
        s4 = await sa_store.get_unsummarized_tweets(until=datetime(2050, 3, 1, tzinfo=timezone.utc))
        assert {t["tweet_id"] for t in f4} == {"1", "4"}  # tweet3 恰在 until 半开排除
        assert f4 == s4

        # limit 夹:limit=1 取 DESC 头(tweet3)
        f5 = await file_store.get_unsummarized_tweets(limit=1)
        s5 = await sa_store.get_unsummarized_tweets(limit=1)
        assert [t["tweet_id"] for t in f5] == ["3"]
        assert f5 == s5

        # created_at aware → ...+00:00(两侧同形态)
        assert f[0]["created_at"] == "2050-03-01T00:00:00+00:00"
        assert s[0]["created_at"] == "2050-03-01T00:00:00+00:00"
    finally:
        await cleanup()


# ---- read path ② get_tweet_origins: 6 字段(CR-023)file vs sqlalchemy(controlled) -

@pytest.mark.asyncio
async def test_origins_six_fields_file_vs_sqlalchemy_controlled(monkeypatch, tmp_path):
    """同一 seed 数据,file 与 sqlalchemy 两实现的 get_tweet_origins 返回 6 字段 dict 逐字一致
    (CR-023:text/referenced_tweet_text/reference_type/referenced_tweet_id/author_username/
    referenced_tweet_author_username),reference_type 为字符串。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))
    from src.data_layer.provider import get_summarization_read_repo

    tweets = [
        # 转推:6 字段全非空,reference_type=retweeted
        _tweet("1", "bob", text="t1", reference_type=ReferenceType.retweeted,
               referenced_tweet_text="orig", referenced_tweet_id="999",
               referenced_tweet_author_username="orig_a"),
        # 原创:referenced_* 为 None,reference_type None,author_username 仍带出
        _tweet("2", "alice", text="t2"),
    ]

    # file 侧
    file_store = get_summarization_read_repo()
    await file_store.seed_tweets(tweets)
    file_origins = await file_store.get_tweet_origins(["1", "2", "404"])

    # sqlalchemy 侧(temp sqlite)
    sa_store, session, cleanup = await _make_sqlite_sa_store(tmp_path)
    try:
        await _sa_seed_tweets(session, tweets)
        sa_origins = await sa_store.get_tweet_origins(["1", "2", "404"])

        # 缺失 id(404)不在 map;两侧逐字一致
        assert set(file_origins) == {"1", "2"}
        assert file_origins == sa_origins

        # 转推条 6 字段全保真
        assert file_origins["1"] == {
            "text": "t1",
            "referenced_tweet_text": "orig",
            "reference_type": "retweeted",
            "referenced_tweet_id": "999",
            "author_username": "bob",
            "referenced_tweet_author_username": "orig_a",
        }
        # 原创条:新增 3 字段中 author_username 带出、其余 None
        assert file_origins["2"] == {
            "text": "t2",
            "referenced_tweet_text": None,
            "reference_type": None,
            "referenced_tweet_id": None,
            "author_username": "alice",
            "referenced_tweet_author_username": None,
        }
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_load_tweets_file_mode_returns_six_fields(monkeypatch, tmp_path):
    """接线后:file 模式下 SummarizationService._load_tweets 经 provider 门面返回 6 字段 dict,
    与 _process_single_tweet 消费方(text/reference_type/referenced_tweet_id/referenced_tweet_text/
    author_username/referenced_tweet_author_username)对齐 → file 模式可跑、6 字段齐全。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))

    # 先经文件层 store 播种一条转推
    from src.data_layer.provider import get_summarization_read_repo

    seeder = get_summarization_read_repo()
    await seeder.seed_tweets([
        _tweet("t1", "bob", text="hello", reference_type=ReferenceType.retweeted,
               referenced_tweet_text="orig", referenced_tweet_id="rt999",
               referenced_tweet_author_username="orig_a"),
    ])

    # 构造 SummarizationService(_load_tweets 在 file 模式忽略 session/session_factory)
    from src.summarization.services.summarization_service import SummarizationService

    service = SummarizationService(session_factory=None, providers=[])  # type: ignore[arg-type]
    out = await service._load_tweets(["t1"])

    assert set(out) == {"t1"}
    # 消费方(_process_single_tweet 约 405-470)用到的 6 键全部存在且正确
    assert out["t1"] == {
        "text": "hello",
        "referenced_tweet_text": "orig",
        "reference_type": "retweeted",          # 字符串,_determine_tweet_type 比较 == "retweeted"
        "referenced_tweet_id": "rt999",
        "author_username": "bob",
        "referenced_tweet_author_username": "orig_a",
    }


# ---- read path ② get_tweet_origins: file(data_migrated) vs sqlalchemy(pg) -

_DATA_MIGRATED = Path(__file__).resolve().parents[2] / "data_migrated"


async def _pg_available_async():
    """真实 pg 可达 + data_migrated 存在 → 跑真实 apples-to-apples,否则 skip。

    在测试 loop 内 inline ping(不用 asyncio.run,避开 running-loop 冲突)。
    """
    if not _DATA_MIGRATED.exists():
        return False
    try:
        from sqlalchemy import text

        from src.database.async_session import get_async_session_maker, reset_async_engine

        reset_async_engine()
        sm = get_async_session_maker()
        async with sm() as s:
            await s.execute(text("SELECT 1"))
        reset_async_engine()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_origins_file_vs_sqlalchemy_real_data(monkeypatch):
    """对从 data_migrated 抽样的真实 tweet_id,file(data_migrated)与 sqlalchemy(pg)返回 dict 一致。"""
    if not await _pg_available_async():
        pytest.skip("真实 pg 不可达或 data_migrated 缺失,跳过 origins 真数据 apples-to-apples")

    from src.database.async_session import get_async_session_maker, reset_async_engine

    # ── file 侧:读 data_migrated,先抽样真实 tweet_id ──
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(_DATA_MIGRATED))
    from src.data_layer.provider import get_summarization_read_repo

    file_store = get_summarization_read_repo()
    all_tweets = await file_store._tweets.get_all_tweets()
    assert all_tweets, "data_migrated 无推文,无法抽样"
    # 真实抽样:取若干含/不含 referenced 的真实 id(独立数源,非固定计数)
    sample_ids = [t.tweet_id for t in all_tweets[:8]]
    file_origins = await file_store.get_tweet_origins(sample_ids)

    # ── sqlalchemy 侧:读真实 pg ──
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    reset_async_engine()
    try:
        sm = get_async_session_maker()
        async with sm() as session:
            sa_store = get_summarization_read_repo(session)
            sa_origins = await sa_store.get_tweet_origins(sample_ids)
    finally:
        reset_async_engine()

    # 这些抽样 id 在两源都应命中(data_migrated 是 pg 的子集快照);取交集严格逐字比对
    common = set(file_origins) & set(sa_origins)
    assert common, "抽样 tweet_id 在 file 与 pg 无交集,无法 apples-to-apples"
    for tid in common:
        assert file_origins[tid] == sa_origins[tid], (
            f"tweet {tid} origin 不一致: file={file_origins[tid]} pg={sa_origins[tid]}"
        )

    # 空入参短路两侧都 {}
    assert await file_store.get_tweet_origins([]) == {}


# ---- Step 5 零变化实证:适配器 dict == 原 76ca702 内联 raw 查询 dict ----------

@pytest.mark.asyncio
async def test_default_mode_zero_change_vs_original_raw_query(tmp_path):
    """默认 sqlalchemy 模式下,适配器产 dict 经 success_response 序列化 == 76ca702 原内联 raw 查询逻辑
    产 dict 经 success_response 序列化(逐字),实证接线零行为变化。"""
    from sqlalchemy import select

    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm

    sa_store, session, cleanup = await _make_sqlite_sa_store(tmp_path)
    try:
        tweets = [
            _tweet("1", "alice", created=datetime(2050, 1, 1, tzinfo=timezone.utc), text="a1",
                   author_display_name="Alice"),
            _tweet("2", "alice", created=datetime(2050, 5, 1, tzinfo=timezone.utc), text="a2"),
            _tweet("3", "bob", created=datetime(2050, 3, 1, tzinfo=timezone.utc), text="b3",
                   reference_type=ReferenceType.retweeted, referenced_tweet_text="orig",
                   referenced_tweet_author_username="orig_a"),
        ]
        await _sa_seed_tweets(session, tweets)
        await _sa_seed_summaries(session, [_summary("s2", "2")])  # tweet2 已摘要

        # === 原 76ca702 内联 raw 查询逻辑(逐字复刻,created_at 放裸 datetime)===
        since_dt = until_dt = None
        author = None
        limit = 50
        clamped_limit = min(max(limit, 1), 200)
        stmt = (
            select(
                TweetOrm.tweet_id, TweetOrm.text, TweetOrm.author_username,
                TweetOrm.author_display_name, TweetOrm.reference_type,
                TweetOrm.referenced_tweet_text, TweetOrm.referenced_tweet_author_username,
                TweetOrm.created_at,
            )
            .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
            .where(SummaryOrm.summary_id == None)  # noqa: E711
        )
        if since_dt:
            stmt = stmt.where(TweetOrm.created_at >= since_dt)
        if until_dt:
            stmt = stmt.where(TweetOrm.created_at < until_dt)
        if author:
            stmt = stmt.where(TweetOrm.author_username == author)
        stmt = stmt.order_by(TweetOrm.created_at.desc()).limit(clamped_limit)
        rows = (await session.execute(stmt)).fetchall()
        original_tweets = []
        for row in rows:
            m = row._mapping
            original_tweets.append({
                "tweet_id": m["tweet_id"], "text": m["text"],
                "author_username": m["author_username"],
                "author_display_name": m["author_display_name"],
                "reference_type": m["reference_type"],
                "referenced_tweet_text": m["referenced_tweet_text"],
                "referenced_tweet_author_username": m["referenced_tweet_author_username"],
                "created_at": m["created_at"],   # 裸 datetime(原工具行为)
            })
        original_json = success_response({"tweets": original_tweets, "count": len(original_tweets)})

        # === 适配器逻辑(created_at 经 _dt_to_iso 字符串)===
        adapter_tweets = await sa_store.get_unsummarized_tweets()
        adapter_json = success_response({"tweets": adapter_tweets, "count": len(adapter_tweets)})

        # 7 字段 + 反连接 + DESC 序逐字一致(排除 created_at —— 见下文 created_at 单独证)。
        # ⚠️ created_at 在 SQLite 上有伪差异:DateTime(timezone=True) 在 sqlite 落盘丢 tz、
        #    读回是 naive → 原 .isoformat() 出 "...T00:00:00"(无 offset)、适配器 _dt_to_iso 补 "+00:00"。
        #    这是 **SQLite 测试基底** 的产物,非真实 pg 行为(pg timestamptz 经 asyncpg 读回是 aware
        #    UTC,两侧都 ...+00:00 —— 见 test_created_at_equivalence_on_aware 直接证)。
        def _drop_created(j):
            d = json.loads(j)
            for t in d["data"]["tweets"]:
                t.pop("created_at", None)
            return d

        assert _drop_created(adapter_json) == _drop_created(original_json), (
            f"零变化破坏(非 created_at 字段):\n原 ={original_json}\n适配器={adapter_json}"
        )
        assert json.loads(adapter_json)["data"]["count"] == 2  # tweet2 被反连接排除
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_created_at_equivalence_on_aware_datetime():
    """created_at 零变化的真实判据:对 **aware UTC datetime**(pg timestamptz 经 asyncpg 读回的实际形态),
    原工具 success_response.isoformat() 与适配器 _dt_to_iso 产 **逐字一致** 的 ...+00:00 串。

    (上一个测试在 SQLite 上 created_at 有伪差异是基底丢 tz 所致;真实 pg 走这条不变量。)"""
    from src.data_layer._summarization_read_sqlalchemy import _dt_to_iso

    # asyncpg 对 timestamptz 永远返回 tzinfo=timezone.utc 的 aware datetime(本会话已实测核验)
    aware = datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc)

    # 原工具:裸 datetime → success_response 用 _default_serializer 调 .isoformat()
    original = success_response({"created_at": aware})
    # 适配器:_dt_to_iso 串
    adapter = success_response({"created_at": _dt_to_iso(aware)})

    assert original == adapter
    assert "2026-01-01T12:30:00+00:00" in adapter
