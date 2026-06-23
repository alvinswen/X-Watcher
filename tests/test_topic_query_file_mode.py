"""topic 跨域读门面(_query_tweets)在 XWATCHER_DATA_LAYER=file 下走文件层。

复刻 `src/topic/services/topic_summary_service.py` 的 `_query_tweets` 内联的那段直查
ORM(TweetOrm LEFT JOIN SummaryOrm)聚合查询,file 模式下不依赖 ORM,改组合既有 file
store(FileTweetStore + FileSummaryStore)在 Python 槽内做过滤/outerjoin/排序:

- 作者名**大小写不敏感**(func.lower(author).in_([lowered]))——与 article 门面精确匹配不同。
- 时间窗**闭区间** created_at >= start AND created_at <= end(两端都含,end 是 <= 非 <)。
- outerjoin summary 取 translation_text(无 summary 的 tweet → translation=None)。
- 排序 created_at ASC。
- 返回 dict 键:tweet_id, text, author, created_at, translation,
  referenced_tweet_text, referenced_tweet_author_username。

⚠️⚠️ 核心:created_at 必须返回 **naive-UTC 裸 datetime**(不是 iso 串)。原 pg 路径返回
naive datetime(str()="2026-02-18 03:30:00",无时区);file domain 读回是 aware-UTC
(str()="...+00:00")。门面把 created_at 归一为 naive-UTC(_as_utc 再 .replace(tzinfo=None)),
与 pg naive 形态字节一致。这关系到下游 _build_prompt 的 f-string 文本与跨域排序。

⚠️ 无 round 陷阱豁免:本片是过滤/outerjoin/排序,无除法分桶,SQLite 是有效 oracle。
跨模式对账用 1 tweet : ≤1 summary(严格逐 dict 相等);多 summary fan-out 的多行语义
另用 file-only 测试覆盖(同 created_at 时 summary 间的 tie-order 是已知限制)。
"""
from datetime import datetime, timedelta, timezone

import pytest


# ── 种子助手 ───────────────────────────────────────────────


def _tweet(tid, author, created_at, text="hello world",
           ref_text=None, ref_author=None):
    from src.scraper.domain.models import Tweet
    return Tweet(
        tweet_id=tid, text=text, created_at=created_at, author_username=author,
        author_display_name=f"{author} disp",
        referenced_tweet_text=ref_text,
        referenced_tweet_author_username=ref_author,
    )


def _summary(tid, translation, sid=None):
    from src.summarization.domain.models import SummaryRecord
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return SummaryRecord(
        summary_id=sid or f"sum-{tid}",
        tweet_id=tid,
        summary_text="zh summary",
        translation_text=translation,
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
async def test_query_tweets_basic_outerjoin_asc(monkeypatch, tmp_path):
    """作者过滤 + 闭区间时间窗 + outerjoin translation(无 summary→None)+ ASC。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("t1", "alice", base + timedelta(hours=3)),  # 有 summary
        _tweet("t2", "alice", base + timedelta(hours=1)),  # 无 summary
        _tweet("t3", "bob", base + timedelta(hours=2)),    # 作者不在列表 → 排除
    ])
    await _seed_summaries(tmp_path, [_summary("t1", "译文 t1")])

    from src.data_layer.provider import get_topic_query_repo

    rows = await get_topic_query_repo().query_tweets(
        ["alice"], base, base + timedelta(hours=24))
    # ASC by created_at:t2(h1) 在 t1(h3) 前;t3 排除(作者 bob)
    assert [r["tweet_id"] for r in rows] == ["t2", "t1"]
    assert rows[0]["translation"] is None       # t2 无 summary
    assert rows[1]["translation"] == "译文 t1"   # t1 outerjoin 取 translation
    assert rows[0]["author"] == "alice"
    # 返回 dict 键集合
    assert set(rows[0].keys()) == {
        "tweet_id", "text", "author", "created_at", "translation",
        "referenced_tweet_text", "referenced_tweet_author_username",
    }


@pytest.mark.asyncio
async def test_query_tweets_author_case_insensitive(monkeypatch, tmp_path):
    """作者名大小写不敏感:func.lower(author).in_([lowered])。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("u1", "Alice", base + timedelta(hours=1)),
        _tweet("u2", "ALICE", base + timedelta(hours=2)),
        _tweet("u3", "alice", base + timedelta(hours=3)),
        _tweet("u4", "carol", base + timedelta(hours=4)),
    ])
    from src.data_layer.provider import get_topic_query_repo

    # 传 "alice" 应匹配 Alice/ALICE/alice 三条(大小写不敏感),carol 排除
    rows = await get_topic_query_repo().query_tweets(
        ["alice"], base, base + timedelta(hours=24))
    assert [r["tweet_id"] for r in rows] == ["u1", "u2", "u3"]
    # 传混合大小写 username 也应归一匹配
    rows2 = await get_topic_query_repo().query_tweets(
        ["AliCe"], base, base + timedelta(hours=24))
    assert [r["tweet_id"] for r in rows2] == ["u1", "u2", "u3"]


@pytest.mark.asyncio
async def test_query_tweets_closed_interval_boundaries(monkeypatch, tmp_path):
    """闭区间:start_time 边界含、end_time 边界含(end 是 <= 不是 <)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    start = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 19, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("before", "alice", start - timedelta(seconds=1)),   # 早于窗口 → 排除
        _tweet("at_start", "alice", start),                        # = start → 含
        _tweet("mid", "alice", start + timedelta(hours=5)),        # 窗内
        _tweet("at_end", "alice", end),                            # = end → 含(闭区间)
        _tweet("after", "alice", end + timedelta(seconds=1)),      # 晚于窗口 → 排除
    ])
    from src.data_layer.provider import get_topic_query_repo

    rows = await get_topic_query_repo().query_tweets(["alice"], start, end)
    # 两端边界都含,窗外排除
    assert [r["tweet_id"] for r in rows] == ["at_start", "mid", "at_end"]


@pytest.mark.asyncio
async def test_query_tweets_created_at_is_naive_utc(monkeypatch, tmp_path):
    """⚠️ created_at 必须是 naive-UTC 裸 datetime(tzinfo is None),与 pg 形态一致。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 3, 30, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [_tweet("t1", "alice", base)])
    from src.data_layer.provider import get_topic_query_repo

    rows = await get_topic_query_repo().query_tweets(
        ["alice"], base - timedelta(hours=1), base + timedelta(hours=1))
    ca = rows[0]["created_at"]
    assert isinstance(ca, datetime)
    assert ca.tzinfo is None                          # naive
    assert str(ca) == "2026-02-18 03:30:00"           # 无 +00:00 后缀,与 pg naive 一致
    assert ca == datetime(2026, 2, 18, 3, 30, 0)      # 值=UTC 裸时刻


@pytest.mark.asyncio
async def test_query_tweets_referenced_fields(monkeypatch, tmp_path):
    """referenced_tweet_text / referenced_tweet_author_username 透传。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("t1", "alice", base + timedelta(hours=1),
               ref_text="原推正文很长很长", ref_author="origauthor"),
    ])
    from src.data_layer.provider import get_topic_query_repo

    rows = await get_topic_query_repo().query_tweets(
        ["alice"], base, base + timedelta(hours=24))
    assert rows[0]["referenced_tweet_text"] == "原推正文很长很长"
    assert rows[0]["referenced_tweet_author_username"] == "origauthor"


@pytest.mark.asyncio
async def test_query_tweets_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    from src.data_layer.provider import get_topic_query_repo

    assert await get_topic_query_repo().query_tweets(
        ["nobody"], base, base + timedelta(hours=24)) == []


@pytest.mark.asyncio
async def test_query_tweets_multi_summary_fanout(monkeypatch, tmp_path):
    """outerjoin 多重性:一个 tweet 有多条 summary → 原 SQL result.all() 产多行。
    file 门面忠实复刻:t1 有 2 条 summary → 结果含 2 行 t1(各带对应 translation)。

    schema 上 summaries.tweet_id 无 unique 约束,故多 summary 在数据层可能存在;
    原 _query_tweets 用 result.all() 非 scalar_one_or_none,会 fan-out 多行。
    """
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [_tweet("t1", "alice", base + timedelta(hours=1))])
    await _seed_summaries(tmp_path, [
        _summary("t1", "译文A", sid="s-a"),
        _summary("t1", "译文B", sid="s-b"),
    ])
    from src.data_layer.provider import get_topic_query_repo

    rows = await get_topic_query_repo().query_tweets(
        ["alice"], base, base + timedelta(hours=24))
    assert len(rows) == 2                               # fan-out 多行
    assert all(r["tweet_id"] == "t1" for r in rows)
    assert {r["translation"] for r in rows} == {"译文A", "译文B"}


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
async def test_cross_mode_query_tweets_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite)返回**完全相同**的 list[dict],含
    created_at 的类型(naive datetime)与值——验证 naive-UTC 归一的关键。

    用 1 tweet : ≤1 summary(严格逐 dict 相等;多 summary fan-out tie-order 见 file-only 测试)。
    作者大小写混搭 + 闭区间边界 + 有/无 translation 全覆盖。
    """
    start = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 19, 0, 0, 0, tzinfo=timezone.utc)
    # 互异 created_at(避 fan-out 外 tie);作者大小写混搭;at_end 含闭区间边界
    tweet_specs = [
        ("c1", "Alice", start + timedelta(hours=2), "正文1", "ref1", "ra1"),
        ("c2", "alice", start, "正文2", None, None),                  # = start 边界
        ("c3", "ALICE", end, "正文3", None, None),                    # = end 边界(闭区间含)
        ("c4", "bob", start + timedelta(hours=1), "正文4", None, None),  # 作者过滤掉
        ("c5", "alice", end + timedelta(hours=1), "正文5", None, None),  # 窗外排除
    ]
    summary_specs = [("c1", "译文1"), ("c3", "译文3")]  # c2 无 summary→None

    # ── 文件层种子 ──
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [
        _tweet(t, a, c, text=tx, ref_text=rt, ref_author=ra)
        for (t, a, c, tx, rt, ra) in tweet_specs
    ])
    await _seed_summaries(tmp_path, [_summary(t, tr) for (t, tr) in summary_specs])

    # ── sqlalchemy(SQLite)种子 ──
    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm
    engine, session = await _build_sqlite_session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for (t, a, c, tx, rt, ra) in tweet_specs:
        # pg 路径存 naive UTC datetime
        session.add(TweetOrm(
            tweet_id=t, text=tx, created_at=c.replace(tzinfo=None),
            db_created_at=now, author_username=a, author_display_name=f"{a} disp",
            media=None, referenced_tweet_text=rt, referenced_tweet_author_username=ra,
        ))
    for (t, tr) in summary_specs:
        session.add(SummaryOrm(
            summary_id=f"sum-{t}", tweet_id=t, summary_text="zh", translation_text=tr,
            model_provider="openrouter", model_name="m",
            prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0,
            content_hash=f"h-{t}", created_at=now, updated_at=now,
        ))
    await session.commit()

    from src.data_layer.provider import get_topic_query_repo

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_rows = await get_topic_query_repo().query_tweets(["alice"], start, end)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_rows = await get_topic_query_repo(session).query_tweets(["alice"], start, end)

    # 完全相同的 list[dict](含 created_at 的类型与值)
    assert f_rows == s_rows
    assert [r["tweet_id"] for r in f_rows] == ["c2", "c1", "c3"]  # ASC
    # created_at 在两模式都是 naive datetime 且逐字段相等
    for fr, sr in zip(f_rows, s_rows):
        assert fr["created_at"].tzinfo is None
        assert sr["created_at"].tzinfo is None
        assert type(fr["created_at"]) is type(sr["created_at"])
        assert fr["created_at"] == sr["created_at"]

    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_mode_prompt_render_equivalence(monkeypatch, tmp_path):
    """prompt 渲染等价:两模式 tweets_data 喂给真实 _build_prompt,prompt 文本一致。
    这是 created_at naive 归一的端到端证据(str(created_at) 插值进 prompt)。"""
    start = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 19, 0, 0, 0, tzinfo=timezone.utc)
    tweet_specs = [
        ("p1", "alice", start + timedelta(hours=3), "first tweet body", None, None),
        ("p2", "alice", start + timedelta(hours=1), "second tweet body", None, None),
    ]
    summary_specs = [("p1", "译文 p1")]

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [
        _tweet(t, a, c, text=tx) for (t, a, c, tx, _, _) in tweet_specs])
    await _seed_summaries(tmp_path, [_summary(t, tr) for (t, tr) in summary_specs])

    from src.scraper.infrastructure.models import TweetOrm
    from src.summarization.infrastructure.models import SummaryOrm
    engine, session = await _build_sqlite_session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for (t, a, c, tx, _, _) in tweet_specs:
        session.add(TweetOrm(
            tweet_id=t, text=tx, created_at=c.replace(tzinfo=None), db_created_at=now,
            author_username=a, author_display_name=f"{a} disp", media=None))
    for (t, tr) in summary_specs:
        session.add(SummaryOrm(
            summary_id=f"sum-{t}", tweet_id=t, summary_text="zh", translation_text=tr,
            model_provider="openrouter", model_name="m",
            prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0,
            content_hash=f"h-{t}", created_at=now, updated_at=now))
    await session.commit()

    from src.data_layer.provider import get_topic_query_repo
    from src.topic.services.topic_summary_service import TopicSummaryService

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_rows = await get_topic_query_repo().query_tweets(["alice"], start, end)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_rows = await get_topic_query_repo(session).query_tweets(["alice"], start, end)

    svc = TopicSummaryService(providers=[])
    f_prompt, _, _ = svc._build_prompt(f_rows, ["alice"], 24, start, end, tz_offset=0)
    s_prompt, _, _ = svc._build_prompt(s_rows, ["alice"], 24, start, end, tz_offset=0)
    assert f_prompt == s_prompt
    # 证 prompt 内时间戳无 +00:00 后缀(naive 形态)
    assert "+00:00" not in f_prompt

    await session.close()
    await engine.dispose()


# ── 服务层接线点 file 模式可跑 ──────────────────────────────


@pytest.mark.asyncio
async def test_service_query_tweets_delegates_file_mode(monkeypatch, tmp_path):
    """_query_tweets 委派后 file 模式可跑:session 被门面忽略,从文件层取数据。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("svc1", "alice", base + timedelta(hours=2)),
        _tweet("svc2", "alice", base + timedelta(hours=1)),
    ])
    await _seed_summaries(tmp_path, [_summary("svc1", "译文 svc1")])

    from src.topic.services.topic_summary_service import TopicSummaryService

    svc = TopicSummaryService(providers=[])
    # session 传 None:file 模式门面忽略 session,不应崩(证明已委派 provider)
    rows = await svc._query_tweets(None, ["alice"], base, base + timedelta(hours=24))
    assert [r["tweet_id"] for r in rows] == ["svc2", "svc1"]  # ASC
    assert rows[1]["translation"] == "译文 svc1"
    assert rows[0]["created_at"].tzinfo is None


# ── 故障注入 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faultinj_created_at_not_normalized(monkeypatch, tmp_path):
    """故意不归一 created_at(让 file 门面返回 aware datetime)→ 与 pg naive 不一致 → 断言能抓到。

    通过 monkeypatch 替换门面的归一函数为恒等(直接返回 domain 的 aware datetime),
    复现"漏归一 created_at"的实现 bug:此时 file 返回 aware(tzinfo 非 None),
    跨模式对账会暴露差异。
    """
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2026, 2, 18, 3, 30, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [_tweet("t1", "alice", base)])

    from src.data_layer.provider import get_topic_query_repo

    # 正确行为:naive
    rows = await get_topic_query_repo().query_tweets(
        ["alice"], base - timedelta(hours=1), base + timedelta(hours=1))
    assert rows[0]["created_at"].tzinfo is None

    # 注入 bug:把门面的 _naive_utc 归一替换成恒等(返回 aware)
    import src.topic.infrastructure.topic_query_read_repository as mod

    def _broken_naive_utc(dt):
        return dt  # 漏归一:直接返回 domain 的 aware datetime

    monkeypatch.setattr(mod, "_naive_utc", _broken_naive_utc)
    buggy = await get_topic_query_repo().query_tweets(
        ["alice"], base - timedelta(hours=1), base + timedelta(hours=1))
    # bug 下 created_at 带时区 → 与正确 naive 形态不同,证明测试对归一敏感
    assert buggy[0]["created_at"].tzinfo is not None
    assert str(buggy[0]["created_at"]) != "2026-02-18 03:30:00"


@pytest.mark.asyncio
async def test_faultinj_closed_interval_vs_half_open(monkeypatch, tmp_path):
    """故意把闭区间写成半开(end 用 <)→ end 边界推文丢失 → 断言翻红。

    monkeypatch 门面的 end 比较谓词为半开,验证测试对"闭区间含 end 边界"敏感。
    """
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    start = datetime(2026, 2, 18, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 19, 0, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("mid", "alice", start + timedelta(hours=5)),
        _tweet("at_end", "alice", end),  # 闭区间应含
    ])
    from src.data_layer.provider import get_topic_query_repo

    # 正确:闭区间含 at_end
    rows = await get_topic_query_repo().query_tweets(["alice"], start, end)
    assert [r["tweet_id"] for r in rows] == ["mid", "at_end"]

    # 注入 bug:把门面的闭区间判定函数替换成半开(end 用 <)
    import src.topic.infrastructure.topic_query_read_repository as mod
    orig = mod._in_window

    def _broken_in_window(ts, lo, hi):
        return lo <= ts < hi  # 半开:漏 end 边界

    monkeypatch.setattr(mod, "_in_window", _broken_in_window)
    buggy = await get_topic_query_repo().query_tweets(["alice"], start, end)
    assert [r["tweet_id"] for r in buggy] == ["mid"]  # at_end 丢失
    assert buggy != rows
    monkeypatch.setattr(mod, "_in_window", orig)
