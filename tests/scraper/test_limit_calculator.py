"""LimitCalculator 单元测试。

测试动态 limit 计算逻辑的各种场景。
"""

from datetime import datetime, timezone

import pytest

from src.scraper.domain.fetch_stats import FetchStats
from src.scraper.services.limit_calculator import LimitCalculator


@pytest.fixture
def calculator():
    """创建默认配置的 LimitCalculator。"""
    return LimitCalculator(
        default_limit=100,
        min_limit=10,
        max_limit=300,
        ema_alpha=0.3,
        safety_margin=1.2,
    )


def _make_stats(
    username: str = "testuser",
    total_fetches: int = 5,
    last_fetched_count: int = 100,
    last_new_count: int = 10,
    avg_new_rate: float = 0.1,
    consecutive_empty_fetches: int = 0,
) -> FetchStats:
    """创建测试用 FetchStats。"""
    return FetchStats(
        username=username,
        last_fetch_at=datetime.now(timezone.utc),
        last_fetched_count=last_fetched_count,
        last_new_count=last_new_count,
        total_fetches=total_fetches,
        avg_new_rate=avg_new_rate,
        consecutive_empty_fetches=consecutive_empty_fetches,
    )


class TestCalculateNextLimit:
    """测试 calculate_next_limit 方法。"""

    def test_new_user_returns_default(self, calculator):
        """新用户（无统计数据）返回默认 limit。"""
        assert calculator.calculate_next_limit(None) == 100

    def test_first_fetch_returns_default(self, calculator):
        """首次抓取（total_fetches=0）返回默认 limit。"""
        stats = _make_stats(total_fetches=0)
        assert calculator.calculate_next_limit(stats) == 100

    def test_full_fetch_doubles_limit(self, calculator):
        """满抓取（全是新推文）时翻倍 limit。"""
        stats = _make_stats(
            last_fetched_count=50,
            last_new_count=50,  # 全是新的
            avg_new_rate=0.5,
        )
        result = calculator.calculate_next_limit(stats)
        assert result == 100  # 50 * 2 = 100

    def test_full_fetch_respects_max_limit(self, calculator):
        """满抓取翻倍不超过 max_limit。"""
        stats = _make_stats(
            last_fetched_count=200,
            last_new_count=200,
            avg_new_rate=0.8,
        )
        result = calculator.calculate_next_limit(stats)
        assert result == 300  # 200 * 2 = 400 -> clamped to 300

    def test_consecutive_empty_below_threshold(self, calculator):
        """连续空抓取 < 3 次不触发退避。"""
        stats = _make_stats(
            consecutive_empty_fetches=2,
            last_new_count=5,
            avg_new_rate=0.1,
        )
        result = calculator.calculate_next_limit(stats)
        # 正常计算: 5 / 0.1 * 1.2 = 60
        assert result == 60

    def test_consecutive_empty_triggers_min_limit(self, calculator):
        """连续空抓取 >= 3 次触发退避到最小值。"""
        stats = _make_stats(consecutive_empty_fetches=3)
        result = calculator.calculate_next_limit(stats)
        assert result == 10  # min_limit

    def test_consecutive_empty_5_still_min(self, calculator):
        """连续空抓取 5 次仍然是最小值。"""
        stats = _make_stats(consecutive_empty_fetches=5)
        result = calculator.calculate_next_limit(stats)
        assert result == 10

    def test_normal_calculation(self, calculator):
        """正常情况下基于 EMA 计算。"""
        stats = _make_stats(
            last_new_count=10,
            avg_new_rate=0.2,
        )
        result = calculator.calculate_next_limit(stats)
        # 10 / 0.2 * 1.2 = 60
        assert result == 60

    def test_high_new_rate(self, calculator):
        """高新推文率产生较低 limit。"""
        stats = _make_stats(
            last_new_count=5,
            avg_new_rate=0.5,
        )
        result = calculator.calculate_next_limit(stats)
        # 5 / 0.5 * 1.2 = 12
        assert result == 12

    def test_low_new_rate(self, calculator):
        """低新推文率产生较高 limit。"""
        stats = _make_stats(
            last_new_count=3,
            avg_new_rate=0.01,
        )
        result = calculator.calculate_next_limit(stats)
        # 3 / 0.01 * 1.2 = 360 -> clamped to 300
        assert result == 300

    def test_respects_min_limit(self, calculator):
        """结果不低于 min_limit。"""
        stats = _make_stats(
            last_new_count=1,
            avg_new_rate=0.9,
        )
        result = calculator.calculate_next_limit(stats)
        # 1 / 0.9 * 1.2 = 1.33 -> clamped to 10
        assert result == 10

    def test_zero_avg_rate_with_no_empty_threshold(self, calculator):
        """avg_new_rate=0 但未达到空抓取阈值时返回默认值。"""
        stats = _make_stats(
            avg_new_rate=0.0,
            last_new_count=0,
            consecutive_empty_fetches=1,
        )
        result = calculator.calculate_next_limit(stats)
        assert result == 100  # fallback to default


class TestUpdateStatsAfterFetch:
    """测试 update_stats_after_fetch 方法。"""

    def test_new_user_creates_stats(self, calculator):
        """首次抓取创建新的统计数据。"""
        result = calculator.update_stats_after_fetch(
            stats=None,
            username="newuser",
            fetched_count=100,
            new_count=80,
        )
        assert result.username == "newuser"
        assert result.total_fetches == 1
        assert result.last_fetched_count == 100
        assert result.last_new_count == 80
        assert result.avg_new_rate == 0.8  # 80/100
        assert result.consecutive_empty_fetches == 0

    def test_new_user_empty_fetch(self, calculator):
        """首次抓取就是空的。"""
        result = calculator.update_stats_after_fetch(
            stats=None,
            username="newuser",
            fetched_count=100,
            new_count=0,
        )
        assert result.total_fetches == 1
        assert result.avg_new_rate == 0.0
        assert result.consecutive_empty_fetches == 1

    def test_ema_update(self, calculator):
        """EMA 正确更新。"""
        old_stats = _make_stats(avg_new_rate=0.5, total_fetches=5)

        result = calculator.update_stats_after_fetch(
            stats=old_stats,
            username="testuser",
            fetched_count=100,
            new_count=10,
        )
        # EMA: 0.3 * (10/100) + 0.7 * 0.5 = 0.03 + 0.35 = 0.38
        assert abs(result.avg_new_rate - 0.38) < 0.001
        assert result.total_fetches == 6

    def test_consecutive_empty_increments(self, calculator):
        """连续空抓取计数递增。"""
        old_stats = _make_stats(consecutive_empty_fetches=2)

        result = calculator.update_stats_after_fetch(
            stats=old_stats,
            username="testuser",
            fetched_count=50,
            new_count=0,
        )
        assert result.consecutive_empty_fetches == 3

    def test_new_tweets_resets_consecutive_empty(self, calculator):
        """有新推文时重置连续空抓取计数。"""
        old_stats = _make_stats(consecutive_empty_fetches=5)

        result = calculator.update_stats_after_fetch(
            stats=old_stats,
            username="testuser",
            fetched_count=50,
            new_count=3,
        )
        assert result.consecutive_empty_fetches == 0

    def test_zero_fetched_preserves_rate(self, calculator):
        """API 返回 0 条时保持原有 rate。"""
        old_stats = _make_stats(avg_new_rate=0.3)

        result = calculator.update_stats_after_fetch(
            stats=old_stats,
            username="testuser",
            fetched_count=0,
            new_count=0,
        )
        assert result.avg_new_rate == 0.3  # unchanged
