"""特征工程单元测试。"""

import pytest
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.services.feature_engineering import build_hourly_distributions
from src.scraper.infrastructure.models import TweetOrm


def _make_tweet(username: str, hour: int, idx: int = 0) -> TweetOrm:
    """创建指定小时的测试推文。"""
    return TweetOrm(
        tweet_id=f"tweet_{username}_{hour}_{idx}",
        text=f"Test tweet at hour {hour}",
        created_at=datetime(2024, 1, 15, hour, 30, 0, tzinfo=timezone.utc),
        author_username=username,
    )


async def _seed_tweets(session: AsyncSession, username: str, hour_counts: dict[int, int]) -> int:
    """为账号插入按小时分布的推文。"""
    total = 0
    for hour, count in hour_counts.items():
        for i in range(count):
            session.add(_make_tweet(username, hour, total + i))
            total += 1
    await session.flush()
    return total


class TestBuildHourlyDistributions:
    """测试 build_hourly_distributions。"""

    async def test_distribution_sums_to_one(self, async_session: AsyncSession):
        """分布向量求和应近似等于 1.0。"""
        # 创建一个有足够推文的账号
        await _seed_tweets(async_session, "user_a", {8: 10, 12: 5, 18: 5, 22: 5})

        distributions, excluded = await build_hourly_distributions(
            async_session, ["user_a"], min_tweets=20
        )

        assert len(distributions) == 1
        assert len(excluded) == 0

        total = sum(distributions[0].distribution)
        assert abs(total - 1.0) < 1e-6

    async def test_distribution_has_24_dimensions(self, async_session: AsyncSession):
        """分布向量应有 24 个维度。"""
        await _seed_tweets(async_session, "user_b", {10: 15, 14: 10})

        distributions, _ = await build_hourly_distributions(
            async_session, ["user_b"], min_tweets=20
        )

        assert len(distributions) == 1
        assert len(distributions[0].distribution) == 24

    async def test_excludes_low_tweet_count(self, async_session: AsyncSession):
        """推文数低于阈值的账号应被排除。"""
        await _seed_tweets(async_session, "low_user", {10: 5})

        distributions, excluded = await build_hourly_distributions(
            async_session, ["low_user"], min_tweets=20
        )

        assert len(distributions) == 0
        assert "low_user" in excluded

    async def test_laplace_smoothing_no_zeros(self, async_session: AsyncSession):
        """Laplace 平滑后不应有零概率。"""
        # 所有推文集中在一个小时
        await _seed_tweets(async_session, "focused_user", {12: 30})

        distributions, _ = await build_hourly_distributions(
            async_session, ["focused_user"], min_tweets=20
        )

        assert len(distributions) == 1
        for val in distributions[0].distribution:
            assert val > 0

    async def test_case_insensitive_matching(self, async_session: AsyncSession):
        """用户名匹配应不区分大小写。"""
        await _seed_tweets(async_session, "MixedCase", {8: 15, 20: 10})

        distributions, _ = await build_hourly_distributions(
            async_session, ["mixedcase"], min_tweets=20
        )

        assert len(distributions) == 1
        assert distributions[0].tweet_count == 25

    async def test_multiple_users(self, async_session: AsyncSession):
        """多个用户应各自独立计算分布。"""
        await _seed_tweets(async_session, "morning_user", {6: 10, 7: 10, 8: 10})
        await _seed_tweets(async_session, "night_user", {20: 10, 21: 10, 22: 10})

        distributions, excluded = await build_hourly_distributions(
            async_session, ["morning_user", "night_user"], min_tweets=20
        )

        assert len(distributions) == 2
        assert len(excluded) == 0

        # morning_user 的分布应在早间小时更高
        morning = next(d for d in distributions if d.username == "morning_user")
        night = next(d for d in distributions if d.username == "night_user")

        morning_peak = max(range(24), key=lambda h: morning.distribution[h])
        night_peak = max(range(24), key=lambda h: night.distribution[h])

        assert morning_peak in (6, 7, 8)
        assert night_peak in (20, 21, 22)

    async def test_empty_usernames(self, async_session: AsyncSession):
        """空用户列表应返回空结果。"""
        distributions, excluded = await build_hourly_distributions(
            async_session, [], min_tweets=20
        )

        assert len(distributions) == 0
        assert len(excluded) == 0
