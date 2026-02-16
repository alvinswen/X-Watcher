"""Browse 查询服务。

实现推文浏览相关的数据库查询逻辑：每日统计、作者列表、推文列表。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm

logger = logging.getLogger(__name__)


class BrowseService:
    """推文浏览查询服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_daily_stats(
        self, year: int, month: int
    ) -> list[dict]:
        """按月查询每日推文数量。

        Args:
            year: 年份
            month: 月份（1-12）

        Returns:
            日期-数量的字典列表，如 [{"date": "2026-02-01", "count": 5}, ...]
        """
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

        stmt = (
            select(
                func.date(TweetOrm.created_at).label("date"),
                func.count().label("count"),
            )
            .where(
                TweetOrm.created_at >= start,
                TweetOrm.created_at < end,
            )
            .group_by(func.date(TweetOrm.created_at))
            .order_by(func.date(TweetOrm.created_at))
        )

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        return [{"date": row.date, "count": row.count} for row in rows]

    async def get_authors(self, date: str) -> list[dict]:
        """查询指定日期有推文的作者列表。

        按最后活跃时间降序排序。通过单独查询获取每个作者最新推文的 display_name。

        Args:
            date: 日期字符串，YYYY-MM-DD 格式

        Returns:
            作者信息字典列表
        """
        day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        # 主查询：按 author_username 分组
        stmt = (
            select(
                TweetOrm.author_username,
                func.count().label("tweet_count"),
                func.max(TweetOrm.created_at).label("last_tweet_at"),
            )
            .where(
                TweetOrm.created_at >= day_start,
                TweetOrm.created_at < day_end,
            )
            .group_by(TweetOrm.author_username)
            .order_by(func.max(TweetOrm.created_at).desc())
        )

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        # 获取每个作者的 display_name（通过查询当天最新推文）
        authors = []
        for row in rows:
            dn_stmt = (
                select(TweetOrm.author_display_name)
                .where(
                    TweetOrm.author_username == row.author_username,
                    TweetOrm.created_at >= day_start,
                    TweetOrm.created_at < day_end,
                )
                .order_by(TweetOrm.created_at.desc())
                .limit(1)
            )
            dn_result = await self._session.execute(dn_stmt)
            display_name = dn_result.scalar()

            authors.append({
                "author_username": row.author_username,
                "author_display_name": display_name,
                "tweet_count": row.tweet_count,
                "last_tweet_at": row.last_tweet_at,
            })

        return authors

    async def get_tweets(
        self,
        date: str,
        author: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        """查询指定日期（可选作者）的推文列表，含摘要和翻译。

        Args:
            date: 日期字符串，YYYY-MM-DD 格式
            author: 作者用户名，None 表示不筛选
            page: 页码（从 1 开始）
            page_size: 每页条数

        Returns:
            (推文字典列表, 总数) 元组
        """
        day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        conditions = [
            TweetOrm.created_at >= day_start,
            TweetOrm.created_at < day_end,
        ]
        if author:
            conditions.append(TweetOrm.author_username == author)

        # COUNT 查询
        count_stmt = (
            select(func.count())
            .select_from(TweetOrm)
            .where(*conditions)
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar() or 0

        # 数据查询：LEFT JOIN summaries
        offset = (page - 1) * page_size
        data_stmt = (
            select(
                TweetOrm.tweet_id,
                TweetOrm.created_at,
                TweetOrm.author_username,
                TweetOrm.author_display_name,
                TweetOrm.text,
                TweetOrm.reference_type,
                TweetOrm.referenced_tweet_id,
                TweetOrm.referenced_tweet_text,
                TweetOrm.referenced_tweet_author_username,
                TweetOrm.media,
                TweetOrm.referenced_tweet_media,
                SummaryOrm.summary_text,
                SummaryOrm.translation_text,
            )
            .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
            .where(*conditions)
            .order_by(TweetOrm.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )

        result = await self._session.execute(data_stmt)
        rows = result.fetchall()

        items = [dict(row._mapping) for row in rows]

        logger.info(
            "Browse 查询完成: date=%s, author=%s, page=%d, total=%d, count=%d",
            date,
            author,
            page,
            total,
            len(items),
        )

        return items, total
