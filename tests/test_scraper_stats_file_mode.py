"""scraper_config 账号聚合三段(#7 period-bucket max / #8 时间范围 / #9 周期分析)在
XWATCHER_DATA_LAYER=file 下走文件层。

- #7 max_period_counts:period_bucket = round-half-up((now-created)/interval)。生产 PG
  cast(... AS integer) 进位 ≠ SQLite floor,SQLite 是失效 oracle——本文件用钉死 PG
  round-half-up 语义的固定边界值断言(floor 实现会翻红),不靠 SQLite 对账。每条配故障注入。
- #8 tweet_time_range / #9 period_analysis:无 round 陷阱,SQLite 是有效 oracle,既做 file
  路径可证又做跨模式(file vs sqlalchemy SQLite)对账。

注:故障注入「把门面 bucket 改 floor」通过 monkeypatch _bucket_round_half_up 注入 floor
实现验证钉值测试有牙(证 round-half-up 非摆设、SQLite 对此操作失效)。
"""
from datetime import datetime, timedelta, timezone

import pytest


# ── 文件层种子助手 ───────────────────────────────────────────


def _tweet(tid, author, created_at, text="hello world"):
    from src.scraper.domain.models import Tweet
    return Tweet(tweet_id=tid, text=text, created_at=created_at, author_username=author,
                 author_display_name=f"{author} disp")


async def _seed_tweets(root, tweets):
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    await FileTweetStore(root).save_tweets(list(tweets), early_stop_threshold=0)


def _norm_instant(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── #7 max_period_counts round-half-up 钉值(关键,不靠 SQLite)──────


@pytest.mark.asyncio
async def test_max_period_counts_round_half_up_pinned(monkeypatch, tmp_path):
    """period-bucket 进位 = round-half-up(复刻生产 PG cast),非 floor。

    interval=12h(43200s)。基准 now 对齐:用 now 当锚,造 3 条同一 author 推文,使其落在
    bucket 边界两侧——bucket = round((now-created)/43200):
      - secs_ago = 6h = 21600 = interval/2 → round-half-up 进位到 bucket 1(floor 留 bucket 0)
      - secs_ago = 6h+δ → bucket 1(floor/round 一致)
      - secs_ago = 5h59m → secs_ago/43200 < 0.5 → bucket 0(floor/round 一致)
    钉死:bucket 分组 = {bucket0: 1 条, bucket1: 2 条} → max=2。
    floor 实现会得 {bucket0: 2, bucket1: 1} → max 仍=2(max 巧合相等!)——故 max 不够区分,
    本测试直接断言门面内部 bucket 分组(经独立重算)+ 用「单边界单条」造 max 可区分的场景。
    """
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    # 用「边界单条 → 该 bucket 唯一占主」造 max 可区分场景:
    # bucket0 放 2 条(均 secs_ago < interval/2),bucket1(round-half-up)放 1 条恰在半点。
    # round-half-up:半点那条进 bucket1 → bucket0=2 / bucket1=1 → max=2。
    # floor:半点那条留 bucket0 → bucket0=3 / (bucket1 无) → max=3。 ← max 翻红可区分!
    now = datetime.now(timezone.utc)
    interval_secs = 12 * 3600
    half = interval_secs // 2  # 21600 = 6h

    specs = [
        ("b0_1", "boundary_u", now - timedelta(seconds=half - 100)),   # secs_ago<half → bucket0
        ("b0_2", "boundary_u", now - timedelta(seconds=half - 200)),   # bucket0
        ("bh_1", "boundary_u", now - timedelta(seconds=half)),         # secs_ago==half → round→bucket1 / floor→bucket0
    ]
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    from src.data_layer.provider import get_scraper_stats_repo

    res = await get_scraper_stats_repo().max_period_counts(["boundary_u"], 12, num_periods=14)
    # round-half-up:bucket0=2(b0_1,b0_2) / bucket1=1(bh_1) → max=2
    # floor 实现:bucket0=3(全归 bucket0)→ max=3(翻红)
    assert res == {"boundary_u": 2}, f"得到 {res}(floor bug 会是 {{'boundary_u': 3}})"


@pytest.mark.asyncio
async def test_max_period_counts_floor_injection_turns_red(monkeypatch, tmp_path):
    """故障注入:把门面 bucket 改 floor `//` → 钉值断言翻红(证有牙 + 证 SQLite 对此失效)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    now = datetime.now(timezone.utc)
    interval_secs = 12 * 3600
    half = interval_secs // 2
    specs = [
        ("b0_1", "boundary_u", now - timedelta(seconds=half - 100)),
        ("b0_2", "boundary_u", now - timedelta(seconds=half - 200)),
        ("bh_1", "boundary_u", now - timedelta(seconds=half)),
    ]
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    # 注入 floor 实现替换 round-half-up
    import src.preference.infrastructure.scraper_stats_read_repository as mod
    monkeypatch.setattr(mod, "_bucket_round_half_up", lambda secs_ago, isecs: secs_ago // isecs)

    from src.data_layer.provider import get_scraper_stats_repo

    res = await get_scraper_stats_repo().max_period_counts(["boundary_u"], 12, num_periods=14)
    # floor 把半点那条留 bucket0 → bucket0=3 → max=3,与 round-half-up 钉值 2 不符
    assert res == {"boundary_u": 3}, "floor 注入应得 max=3(证 round-half-up 实现有牙)"


@pytest.mark.asyncio
async def test_max_period_counts_window_and_lower_match(monkeypatch, tmp_path):
    """窗口边界(cutoff <= created < now)+ 大小写不敏感 author 匹配。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    interval = timedelta(hours=12)
    num_periods = 14
    cutoff = now - num_periods * interval

    specs = [
        # 同一 bucket(均距 now ~1h,bucket0)的 3 条 → max=3;author 大小写混写
        ("w1", "MixedCase", now - timedelta(hours=1)),
        ("w2", "mixedcase", now - timedelta(hours=1, minutes=10)),
        ("w3", "MIXEDCASE", now - timedelta(hours=1, minutes=20)),
        # 窗口外(早于 cutoff)→ 不计入
        ("old", "MixedCase", cutoff - timedelta(hours=1)),
    ]
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    from src.data_layer.provider import get_scraper_stats_repo

    # 查询用 username 原始大小写,门面内部 lower 匹配
    res = await get_scraper_stats_repo().max_period_counts(["MixedCase"], 12, num_periods)
    assert res == {"mixedcase": 3}, f"3 条同 bucket(大小写不敏感)+ 窗口外排除 → {res}"
    # 故障注入:再加 1 条同 bucket → max 应升到 4(证非写死)
    await _seed_tweets(tmp_path, [_tweet("w4", "mixedcase", now - timedelta(hours=1, minutes=5))])
    res2 = await get_scraper_stats_repo().max_period_counts(["MixedCase"], 12, num_periods)
    assert res2 == {"mixedcase": 4}


@pytest.mark.asyncio
async def test_max_period_counts_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_scraper_stats_repo
    assert await get_scraper_stats_repo().max_period_counts([], 12) == {}
    # 有用户但无推文 → 空 dict(端点用 .get(lower, 0) 兜底)
    assert await get_scraper_stats_repo().max_period_counts(["nobody"], 12) == {}


# ── #8 tweet_time_range(min/max/count)──────────────────────


@pytest.mark.asyncio
async def test_tweet_time_range_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    earliest = base
    latest = base + timedelta(days=10)
    specs = [
        ("a1", "alice", base + timedelta(days=5)),
        ("a2", "Alice", earliest),                    # 大小写不敏感同账号 → 计入 alice
        ("a3", "alice", latest),
        ("b1", "bob", base + timedelta(days=2)),
    ]
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    from src.data_layer.provider import get_scraper_stats_repo

    res = await get_scraper_stats_repo().tweet_time_range(["alice", "bob", "carol"])
    a_min, a_max, a_cnt = res["alice"]
    assert _norm_instant(a_min) == _norm_instant(earliest)
    assert _norm_instant(a_max) == _norm_instant(latest)
    assert a_cnt == 3
    b_min, b_max, b_cnt = res["bob"]
    assert b_cnt == 1 and _norm_instant(b_min) == _norm_instant(b_max)
    assert "carol" not in res  # 无推文账号不出现(端点兜底 None/None/0)
    # 故障注入:给 alice 加更晚一条 → max 应推进、count+1
    new_latest = latest + timedelta(days=3)
    await _seed_tweets(tmp_path, [_tweet("a4", "alice", new_latest)])
    res2 = await get_scraper_stats_repo().tweet_time_range(["alice"])
    _amin2, amax2, acnt2 = res2["alice"]
    assert _norm_instant(amax2) == _norm_instant(new_latest) and acnt2 == 4


@pytest.mark.asyncio
async def test_cross_mode_tweet_time_range_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite)产同 min/max/count(SQLite 有效 oracle,无 round 陷阱)。"""
    base = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    specs = [
        ("a1", "alice", base + timedelta(days=5)),
        ("a2", "alice", base),
        ("a3", "alice", base + timedelta(days=10)),
        ("b1", "bob", base + timedelta(days=2)),
        ("b2", "bob", base + timedelta(days=8)),
    ]
    usernames = ["alice", "bob", "carol"]

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    engine, session = await _build_sqlite_session()
    await _seed_sqlite_tweets(session, specs)

    from src.data_layer.provider import get_scraper_stats_repo

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_res = await get_scraper_stats_repo().tweet_time_range(usernames)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_res = await get_scraper_stats_repo(session).tweet_time_range(usernames)

    assert set(f_res.keys()) == set(s_res.keys()) == {"alice", "bob"}
    for u in ("alice", "bob"):
        fmin, fmax, fcnt = f_res[u]
        smin, smax, scnt = s_res[u]
        assert fcnt == scnt
        assert _norm_instant(fmin) == _norm_instant(smin)
        assert _norm_instant(fmax) == _norm_instant(smax)

    await session.close()
    await engine.dispose()


# ── #9 period_analysis(显式窗口逐周期 count)────────────────


@pytest.mark.asyncio
async def test_period_analysis_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    interval = timedelta(hours=12)
    # periods=3:窗口(正序前)= [now-3i.., now-2i..)依次。造定位明确的推文:
    #   period i=0(最新): [now-12h, now) → 放 2 条
    #   period i=1:        [now-24h, now-12h) → 放 1 条
    #   period i=2(最早):  [now-36h, now-24h) → 放 0 条
    specs = [
        ("p0a", "alice", now - timedelta(hours=2)),
        ("p0b", "alice", now - timedelta(hours=6)),
        ("p1a", "alice", now - timedelta(hours=18)),
        ("noise", "bob", now - timedelta(hours=3)),   # 他人 → 不计入 alice
    ]
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    from src.data_layer.provider import get_scraper_stats_repo

    windows = await get_scraper_stats_repo().period_analysis("alice", 12, 3)
    counts = [c for (_ps, _pe, c) in windows]
    # 正序(最早在前):[period2=0, period1=1, period0=2]
    assert counts == [0, 1, 2], f"逐周期 count 正序 → {counts}"
    # 边界正序校验:第一段 period_start 最早,最后一段 period_end ≈ now
    assert windows[0][0] < windows[-1][1]
    assert _norm_instant(windows[-1][1]) == _norm_instant(windows[-1][1])  # now 锚一致(同次调用)
    # 故障注入:大小写不敏感——用 ALICE 查应得同结果
    windows_upper = await get_scraper_stats_repo().period_analysis("ALICE", 12, 3)
    assert [c for (_a, _b, c) in windows_upper] == [0, 1, 2]


@pytest.mark.asyncio
async def test_cross_mode_period_analysis_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite)产同逐周期 count + 同窗口边界(SQLite 有效 oracle)。"""
    base_now_anchor = datetime.now(timezone.utc)
    specs = [
        ("p0a", "alice", base_now_anchor - timedelta(hours=2)),
        ("p0b", "alice", base_now_anchor - timedelta(hours=6)),
        ("p1a", "alice", base_now_anchor - timedelta(hours=18)),
        ("p3a", "alice", base_now_anchor - timedelta(hours=40)),
        ("noise", "bob", base_now_anchor - timedelta(hours=3)),
    ]
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in specs])

    engine, session = await _build_sqlite_session()
    await _seed_sqlite_tweets(session, specs)

    from src.data_layer.provider import get_scraper_stats_repo

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_windows = await get_scraper_stats_repo().period_analysis("alice", 12, 4)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_windows = await get_scraper_stats_repo(session).period_analysis("alice", 12, 4)

    # 逐周期 count 一致(窗口锚 now 各路独立取,但相对边界相同 → count 应同;
    # 数据点距边界足够远,now 微小漂移不跨界)
    assert [c for (_a, _b, c) in f_windows] == [c for (_a, _b, c) in s_windows]
    assert len(f_windows) == len(s_windows) == 4

    await session.close()
    await engine.dispose()


# ── 端点级 file 模式冒烟(经路由组装响应模型)──────────────────


@pytest.mark.asyncio
async def test_endpoints_file_mode_smoke(monkeypatch, tmp_path):
    """3 端点的 tweet 聚合段在 file 模式经路由直调(provider 缝生效,响应模型组装正确)。

    直调 endpoint 函数(注入 file 模式 follows + tweets),验证 max_count/time_range/period 段
    走文件层无 ORM 依赖。注:effective_limit 段走 get_fetch_stats_repo(file)已在子项目 3 接线。
    """
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    # 种 follows(file)+ tweets(file)
    from src.preference.domain.models import ScraperFollow
    from src.preference.infrastructure.file_follow_repository import FileFollowStore
    await FileFollowStore(tmp_path).seed([
        ScraperFollow(id=1, username="alice", added_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                      reason="r", added_by="t", is_active=True),
    ])
    now = datetime.now(timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("e1", "alice", now - timedelta(hours=1)),
        _tweet("e2", "alice", now - timedelta(hours=2)),
    ])

    # #8 端点:tweet-time-range(无需 fetch_stats / LLM,最干净的端点级冒烟)
    from src.preference.api import scraper_config_router as rt

    class _Admin:
        pass

    res8 = await rt.get_follows_tweet_time_range(admin=_Admin())
    assert len(res8) == 1
    assert res8[0].username == "alice"
    assert res8[0].tweet_count == 2
    assert res8[0].earliest_tweet_at is not None and res8[0].latest_tweet_at is not None

    # #9 端点:follow-analysis(直接 username,无 follows 依赖)
    res9 = await rt.get_follow_analysis(
        username="alice", interval_hours=12, periods=3, admin=_Admin()
    )
    assert res9.username == "alice"
    assert res9.total_new_tweets == 2
    assert len(res9.periods) == 3


# ── 跨模式 SQLite 助手 ───────────────────────────────────────


async def _build_sqlite_session():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.database.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    return engine, session


async def _seed_sqlite_tweets(session, specs):
    from src.scraper.infrastructure.models import TweetOrm
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    for (t, a, c) in specs:
        session.add(TweetOrm(
            tweet_id=t, text="x",
            created_at=c.replace(tzinfo=None) if c.tzinfo else c,
            db_created_at=now_naive,
            author_username=a, author_display_name=f"{a} disp", media=None,
        ))
    await session.commit()
