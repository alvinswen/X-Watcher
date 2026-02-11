"""FetchStatsRepository 集成测试。

测试抓取统计的数据库 CRUD 操作。
"""

from datetime import datetime, timezone

import pytest

from src.scraper.domain.fetch_stats import FetchStats
from src.scraper.infrastructure.fetch_stats_repository import FetchStatsRepository


@pytest.mark.asyncio
class TestFetchStatsRepository:
    """FetchStatsRepository 集成测试。"""

    def _make_stats(self, username: str = "testuser", **kwargs) -> FetchStats:
        defaults = dict(
            username=username,
            last_fetch_at=datetime(2026, 2, 11, 12, 0, 0, tzinfo=timezone.utc),
            last_fetched_count=100,
            last_new_count=10,
            total_fetches=5,
            avg_new_rate=0.1,
            consecutive_empty_fetches=0,
        )
        defaults.update(kwargs)
        return FetchStats(**defaults)

    async def test_get_stats_nonexistent(self, async_session):
        """查询不存在的用户返回 None。"""
        repo = FetchStatsRepository(async_session)
        result = await repo.get_stats("nonexistent")
        assert result is None

    async def test_upsert_insert(self, async_session):
        """upsert 插入新记录。"""
        repo = FetchStatsRepository(async_session)
        stats = self._make_stats()

        await repo.upsert_stats(stats)
        await async_session.commit()

        result = await repo.get_stats("testuser")
        assert result is not None
        assert result.username == "testuser"
        assert result.total_fetches == 5
        assert result.avg_new_rate == 0.1

    async def test_upsert_update(self, async_session):
        """upsert 更新已存在的记录。"""
        repo = FetchStatsRepository(async_session)

        # 插入初始数据
        stats = self._make_stats(total_fetches=1, avg_new_rate=0.5)
        await repo.upsert_stats(stats)
        await async_session.commit()

        # 更新
        updated = self._make_stats(total_fetches=2, avg_new_rate=0.3)
        await repo.upsert_stats(updated)
        await async_session.commit()

        result = await repo.get_stats("testuser")
        assert result is not None
        assert result.total_fetches == 2
        assert abs(result.avg_new_rate - 0.3) < 0.001

    async def test_batch_get_stats_empty(self, async_session):
        """空用户名列表返回空字典。"""
        repo = FetchStatsRepository(async_session)
        result = await repo.batch_get_stats([])
        assert result == {}

    async def test_batch_get_stats_mixed(self, async_session):
        """批量查询：部分存在、部分不存在。"""
        repo = FetchStatsRepository(async_session)

        # 插入两个用户的统计
        for name in ["user_a", "user_b"]:
            stats = self._make_stats(username=name)
            await repo.upsert_stats(stats)
        await async_session.commit()

        result = await repo.batch_get_stats(["user_a", "user_b", "user_c"])
        assert len(result) == 2
        assert "user_a" in result
        assert "user_b" in result
        assert "user_c" not in result

    async def test_batch_get_stats_all_missing(self, async_session):
        """批量查询：所有用户都不存在。"""
        repo = FetchStatsRepository(async_session)
        result = await repo.batch_get_stats(["ghost1", "ghost2"])
        assert result == {}
