"""抓取统计数据仓库。

实现抓取统计的数据库 CRUD 操作。
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.domain.fetch_stats import FetchStats
from src.scraper.infrastructure.fetch_stats_models import FetchStatsOrm

logger = logging.getLogger(__name__)


class FetchStatsRepository:
    """抓取统计数据仓库。

    负责抓取统计数据的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_stats(self, username: str) -> FetchStats | None:
        """查询单个用户的抓取统计。

        Args:
            username: Twitter 用户名

        Returns:
            FetchStats | None: 统计数据，不存在时返回 None
        """
        stmt = select(FetchStatsOrm).where(FetchStatsOrm.username == username)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return orm.to_domain()

    async def batch_get_stats(
        self, usernames: list[str]
    ) -> dict[str, FetchStats]:
        """批量查询用户的抓取统计。

        Args:
            usernames: 用户名列表

        Returns:
            dict[str, FetchStats]: 用户名到统计数据的映射
        """
        if not usernames:
            return {}

        stmt = select(FetchStatsOrm).where(
            FetchStatsOrm.username.in_(usernames)
        )
        result = await self._session.execute(stmt)
        orm_list = result.scalars().all()

        return {orm.username: orm.to_domain() for orm in orm_list}

    async def upsert_stats(self, stats: FetchStats) -> None:
        """插入或更新抓取统计。

        如果用户名已存在则更新，否则插入新记录。

        Args:
            stats: 抓取统计数据
        """
        stmt = select(FetchStatsOrm).where(
            FetchStatsOrm.username == stats.username
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.last_fetch_at = stats.last_fetch_at
            existing.last_fetched_count = stats.last_fetched_count
            existing.last_new_count = stats.last_new_count
            existing.total_fetches = stats.total_fetches
            existing.avg_new_rate = stats.avg_new_rate
            existing.consecutive_empty_fetches = stats.consecutive_empty_fetches
        else:
            orm = FetchStatsOrm.from_domain(stats)
            self._session.add(orm)

        await self._session.flush()
