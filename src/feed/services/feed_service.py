"""Feed 查询服务。

实现推文+摘要联合查询逻辑，支持时间区间过滤和可选摘要加载。
"""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.feed.api.schemas import FeedResult
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm

logger = logging.getLogger(__name__)


class FeedService:
    """Feed 查询服务。

    构建并执行推文+摘要联合查询，返回结构化结果。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_feed(
        self,
        since: datetime,
        until: datetime,
        limit: int,
        include_summary: bool = True,
    ) -> FeedResult:
        """查询指定时间区间内的推文。

        Args:
            since: 起始时间（含），过滤 db_created_at >= since
            until: 截止时间（不含），过滤 db_created_at < until
            limit: 最大返回条数
            include_summary: 是否包含摘要和翻译

        Returns:
            FeedResult: 查询结果
        """
        # 1. COUNT 查询：获取满足时间条件的总数
        count_stmt = (
            select(func.count())
            .select_from(TweetOrm)
            .where(
                TweetOrm.db_created_at >= since,
                TweetOrm.db_created_at < until,
            )
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar() or 0

        # 2. 数据查询
        if include_summary:
            data_stmt = (
                select(
                    TweetOrm.tweet_id,
                    TweetOrm.text,
                    TweetOrm.author_username,
                    TweetOrm.author_display_name,
                    TweetOrm.created_at,
                    TweetOrm.db_created_at,
                    TweetOrm.reference_type,
                    TweetOrm.referenced_tweet_id,
                    TweetOrm.media,
                    SummaryOrm.summary_text,
                    SummaryOrm.translation_text,
                )
                .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
                .where(
                    TweetOrm.db_created_at >= since,
                    TweetOrm.db_created_at < until,
                )
                .order_by(TweetOrm.created_at.desc())
                .limit(limit)
            )
        else:
            data_stmt = (
                select(
                    TweetOrm.tweet_id,
                    TweetOrm.text,
                    TweetOrm.author_username,
                    TweetOrm.author_display_name,
                    TweetOrm.created_at,
                    TweetOrm.db_created_at,
                    TweetOrm.reference_type,
                    TweetOrm.referenced_tweet_id,
                    TweetOrm.media,
                )
                .where(
                    TweetOrm.db_created_at >= since,
                    TweetOrm.db_created_at < until,
                )
                .order_by(TweetOrm.created_at.desc())
                .limit(limit)
            )

        result = await self._session.execute(data_stmt)
        rows = result.fetchall()

        # 3. 构建结果字典列表
        items = []
        for row in rows:
            row_dict = dict(row._mapping)
            if not include_summary:
                row_dict["summary_text"] = None
                row_dict["translation_text"] = None
            items.append(row_dict)

        count = len(items)
        has_more = count < total

        logger.info(
            "Feed 查询完成: since=%s, until=%s, total=%d, count=%d, has_more=%s",
            since.isoformat(),
            until.isoformat(),
            total,
            count,
            has_more,
        )

        return FeedResult(
            items=items,
            count=count,
            total=total,
            has_more=has_more,
        )
