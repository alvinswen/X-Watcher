"""Browse 查询服务。

实现推文浏览相关的数据库查询逻辑：每日统计、作者列表、推文列表。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperFollow
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm

logger = logging.getLogger(__name__)


class BrowseService:
    """推文浏览查询服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _local_date_to_utc_range(
        date_str: str, tz_offset: int
    ) -> tuple[datetime, datetime]:
        """将用户本地日期 + tz_offset 转为 UTC 起止时间。

        Args:
            date_str: 用户本地日期字符串，YYYY-MM-DD 格式
            tz_offset: JS ``getTimezoneOffset()`` 的值（分钟），UTC+8 为 -480。
                       含义为 UTC - local，因此 local + offset = UTC。

        Returns:
            (day_start_utc, day_end_utc) 元组
        """
        local_midnight = datetime.strptime(date_str, "%Y-%m-%d")
        utc_start = (local_midnight + timedelta(minutes=tz_offset)).replace(
            tzinfo=timezone.utc
        )
        utc_end = utc_start + timedelta(days=1)
        return utc_start, utc_end

    async def get_daily_stats(
        self, year: int, month: int, tz_offset: int = 0
    ) -> list[dict]:
        """按月查询每日推文数量（按用户本地时区分组）。

        Args:
            year: 年份（用户本地时区）
            month: 月份 1-12（用户本地时区）
            tz_offset: JS ``getTimezoneOffset()`` 的值（分钟），默认 0（UTC）

        Returns:
            日期-数量的字典列表，如 [{"date": "2026-02-01", "count": 5}, ...]
        """
        # 用户本地月份起止 → UTC 范围
        local_start = datetime(year, month, 1)
        if month == 12:
            local_end = datetime(year + 1, 1, 1)
        else:
            local_end = datetime(year, month + 1, 1)

        utc_start = (local_start + timedelta(minutes=tz_offset)).replace(
            tzinfo=timezone.utc
        )
        utc_end = (local_end + timedelta(minutes=tz_offset)).replace(
            tzinfo=timezone.utc
        )

        # SQLite date() 支持修饰符：date(col, '+480 minutes') 将 UTC 时间偏移到用户本地时区后取日期
        # getTimezoneOffset() 返回 UTC-local，取反得到 local = UTC + (-tz_offset) minutes
        offset_modifier = f"{-tz_offset} minutes"
        local_date_expr = func.date(TweetOrm.created_at, offset_modifier)

        stmt = (
            select(
                local_date_expr.label("date"),
                func.count().label("count"),
            )
            .where(
                TweetOrm.created_at >= utc_start,
                TweetOrm.created_at < utc_end,
            )
            .group_by(local_date_expr)
            .order_by(local_date_expr)
        )

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        return [{"date": row.date, "count": row.count} for row in rows]

    async def get_authors(self, date: str, tz_offset: int = 0) -> list[dict]:
        """查询指定日期有推文的作者列表。

        按最后活跃时间降序排序。通过单独查询获取每个作者最新推文的 display_name。

        Args:
            date: 用户本地日期字符串，YYYY-MM-DD 格式
            tz_offset: JS ``getTimezoneOffset()`` 的值（分钟），默认 0

        Returns:
            作者信息字典列表
        """
        day_start, day_end = self._local_date_to_utc_range(date, tz_offset)

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
                    func.lower(TweetOrm.author_username) == row.author_username.lower(),
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

        # 批量查询作者简介（ScraperFollow.reason）
        usernames = [a["author_username"] for a in authors]
        if usernames:
            reason_stmt = (
                select(ScraperFollow.username, ScraperFollow.reason)
                .where(
                    ScraperFollow.username.in_(usernames),
                    ScraperFollow.is_active == True,  # noqa: E712
                )
            )
            reason_result = await self._session.execute(reason_stmt)
            reason_map = {r.username: r.reason for r in reason_result.fetchall()}
        else:
            reason_map = {}

        for author in authors:
            author["reason"] = reason_map.get(author["author_username"])

        return authors

    async def get_tweets(
        self,
        date: str,
        author: str | None,
        page: int,
        page_size: int,
        tz_offset: int = 0,
    ) -> tuple[list[dict], int]:
        """查询指定日期（可选作者）的推文列表，含摘要和翻译。

        Args:
            date: 用户本地日期字符串，YYYY-MM-DD 格式
            author: 作者用户名，None 表示不筛选
            page: 页码（从 1 开始）
            page_size: 每页条数
            tz_offset: JS ``getTimezoneOffset()`` 的值（分钟），默认 0

        Returns:
            (推文字典列表, 总数) 元组
        """
        day_start, day_end = self._local_date_to_utc_range(date, tz_offset)

        conditions = [
            TweetOrm.created_at >= day_start,
            TweetOrm.created_at < day_end,
        ]
        if author:
            conditions.append(func.lower(TweetOrm.author_username) == author.lower())

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
