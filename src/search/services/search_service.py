"""推文搜索服务。

实现多字段关键词搜索，支持作者筛选、时间范围和分页。
"""

import logging
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.infrastructure.models import TweetOrm
from src.search.api.schemas import SearchResult
from src.summarization.infrastructure.models import SummaryOrm

logger = logging.getLogger(__name__)


class SearchService:
    """推文搜索服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_tweets(
        self,
        q: str,
        page: int = 1,
        page_size: int = 20,
        include_summary: bool = True,
        author: str | None = None,
        authors: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SearchResult:
        """搜索推文。

        Args:
            q: 搜索关键词（空格分隔多个关键词，AND 逻辑）
            page: 页码（从 1 开始）
            page_size: 每页条数
            include_summary: 是否包含摘要和翻译
            author: 单作者筛选（大小写不敏感）
            authors: 多作者筛选（大小写不敏感）
            since: 起始时间（含）
            until: 截止时间（不含）

        Returns:
            SearchResult: 搜索结果
        """
        keywords = q.split()

        # 构建过滤条件
        conditions = []

        # 时间范围
        if since:
            conditions.append(TweetOrm.created_at >= since)
        if until:
            conditions.append(TweetOrm.created_at < until)

        # 作者筛选
        if author:
            conditions.append(
                func.lower(TweetOrm.author_username) == author.lower()
            )
        elif authors:
            conditions.append(
                func.lower(TweetOrm.author_username).in_(
                    [a.lower() for a in authors]
                )
            )

        # 关键词条件（每个关键词必须匹配至少一个字段 → AND 逻辑）
        for kw in keywords:
            like_pattern = f"%{kw}%"
            keyword_fields = [
                TweetOrm.text.ilike(like_pattern),
                TweetOrm.referenced_tweet_text.ilike(like_pattern),
            ]
            if include_summary:
                keyword_fields.extend([
                    SummaryOrm.summary_text.ilike(like_pattern),
                    SummaryOrm.translation_text.ilike(like_pattern),
                ])
            conditions.append(or_(*keyword_fields))

        # 搜索始终需要 LEFT JOIN summaries（关键词可能匹配摘要/翻译字段）
        needs_join = include_summary

        # COUNT 查询
        if needs_join:
            count_stmt = (
                select(func.count())
                .select_from(TweetOrm)
                .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
                .where(*conditions)
            )
        else:
            count_stmt = (
                select(func.count())
                .select_from(TweetOrm)
                .where(*conditions)
            )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar() or 0

        # 数据查询
        offset = (page - 1) * page_size

        columns = [
            TweetOrm.tweet_id,
            TweetOrm.text,
            TweetOrm.author_username,
            TweetOrm.author_display_name,
            TweetOrm.created_at,
            TweetOrm.db_created_at,
            TweetOrm.reference_type,
            TweetOrm.referenced_tweet_id,
            TweetOrm.referenced_tweet_text,
            TweetOrm.referenced_tweet_author_username,
            TweetOrm.media,
            TweetOrm.referenced_tweet_media,
        ]
        if include_summary:
            columns.extend([
                SummaryOrm.summary_text,
                SummaryOrm.translation_text,
            ])

        data_stmt = select(*columns)
        if needs_join:
            data_stmt = data_stmt.outerjoin(
                SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id
            )
        data_stmt = (
            data_stmt.where(*conditions)
            .order_by(TweetOrm.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        result = await self._session.execute(data_stmt)
        rows = result.fetchall()

        items = []
        for row in rows:
            row_dict = dict(row._mapping)
            if not include_summary:
                row_dict["summary_text"] = None
                row_dict["translation_text"] = None
            items.append(row_dict)

        logger.info(
            "搜索完成: q=%r, total=%d, page=%d/%d",
            q,
            total,
            page,
            (total + page_size - 1) // page_size if total > 0 else 0,
        )

        return SearchResult(items=items, total=total)
