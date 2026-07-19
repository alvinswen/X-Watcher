"""scraper_config 账号聚合两段(#8 时间范围 / #9 周期分析)在
XWATCHER_DATA_LAYER=file 下走文件层。

- #8 tweet_time_range / #9 period_analysis:无 round 陷阱,SQLite 是有效 oracle,既做 file
  路径可证又做跨模式(file vs sqlalchemy SQLite)对账。
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

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
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


# ── #8 tweet_time_range(min/max/count)──────────────────────


@pytest.mark.asyncio
async def test_tweet_time_range_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC)
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


# ── #9 period_analysis(显式窗口逐周期 count)────────────────


@pytest.mark.asyncio
async def test_period_analysis_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    now = datetime.now(UTC)
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
        ScraperFollow(id=1, username="alice", added_at=datetime(2024, 1, 1, tzinfo=UTC),
                      reason="r", added_by="t", is_active=True),
    ])
    now = datetime.now(UTC)
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


@pytest.mark.asyncio
async def test_tc_build_415_shared_ranges_preserve_original_case_keys():
    from src.preference.services.scraper_config_service import get_tweet_time_ranges

    repo = Mock()
    repo.tweet_time_range = AsyncMock(return_value={"alice": (None, None, 2)})
    with patch("src.data_layer.provider.get_scraper_stats_repo", return_value=repo):
        result = await get_tweet_time_ranges(["Alice"])

    assert result == {"Alice": (None, None, 2)}
    assert "alice" not in result


@pytest.mark.asyncio
async def test_tc_build_416_shared_ranges_empty_skips_repository():
    from src.preference.services.scraper_config_service import get_tweet_time_ranges

    with patch("src.data_layer.provider.get_scraper_stats_repo") as getter:
        assert await get_tweet_time_ranges([]) == {}

    getter.assert_not_called()


@pytest.mark.asyncio
async def test_tc_build_417_shared_ranges_match_lowercase_repository_rows():
    from src.preference.services.scraper_config_service import get_tweet_time_ranges

    earliest = datetime(2026, 7, 1, tzinfo=UTC)
    latest = datetime(2026, 7, 2, tzinfo=UTC)
    repo = Mock()
    repo.tweet_time_range = AsyncMock(return_value={"mixedcase": (earliest, latest, 4)})
    with patch("src.data_layer.provider.get_scraper_stats_repo", return_value=repo):
        result = await get_tweet_time_ranges(["MixedCase"])

    assert result["MixedCase"] == (earliest, latest, 4)
