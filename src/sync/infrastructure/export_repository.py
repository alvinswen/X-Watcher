"""Export 数据读取仓库。

使用同步 Session 批量读取各表数据，支持 content 的 since/until/authors 过滤。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.database.models import ScraperFollow, ScraperScheduleConfig
from src.scraper.infrastructure.article_models import ArticleOrm
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
)


class ExportRepository:
    """从数据库读取可同步数据。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_follows(self) -> list[ScraperFollow]:
        return list(self._session.execute(select(ScraperFollow)).scalars().all())

    def get_schedule_config(self) -> ScraperScheduleConfig | None:
        return self._session.execute(
            select(ScraperScheduleConfig).where(ScraperScheduleConfig.id == 1)
        ).scalar_one_or_none()

    def get_tweets(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        authors: list[str] | None = None,
    ) -> list[TweetOrm]:
        stmt = select(TweetOrm)
        if since:
            stmt = stmt.where(TweetOrm.created_at >= since)
        if until:
            stmt = stmt.where(TweetOrm.created_at <= until)
        if authors:
            stmt = stmt.where(TweetOrm.author_username.in_(authors))
        stmt = stmt.order_by(TweetOrm.created_at)
        return list(self._session.execute(stmt).scalars().all())

    def get_summaries(self, tweet_ids: list[str] | None = None) -> list[SummaryOrm]:
        stmt = select(SummaryOrm)
        if tweet_ids is not None:
            stmt = stmt.where(SummaryOrm.tweet_id.in_(tweet_ids))
        return list(self._session.execute(stmt).scalars().all())

    def get_articles(self, tweet_ids: list[str] | None = None) -> list[ArticleOrm]:
        stmt = select(ArticleOrm)
        if tweet_ids is not None:
            stmt = stmt.where(ArticleOrm.tweet_id.in_(tweet_ids))
        return list(self._session.execute(stmt).scalars().all())

    def get_topics(self) -> list[TopicOrm]:
        """读取所有 topics 及其关联的 accounts 和 summary_tasks（含 summary）。"""
        stmt = (
            select(TopicOrm)
            .options(
                joinedload(TopicOrm.accounts),
                joinedload(TopicOrm.summary_tasks).joinedload(
                    TopicSummaryTaskOrm.summary
                ),
            )
        )
        return list(self._session.execute(stmt).unique().scalars().all())
