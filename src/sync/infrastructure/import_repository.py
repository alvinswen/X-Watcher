"""Import 数据写入仓库。

批量写入 + 冲突检测。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import ScraperFollow
from src.scraper.infrastructure.article_models import ArticleOrm
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.sync.domain.models import ConflictStrategy, ImportStats
from src.sync.infrastructure.serializers import (
    _iso_to_naive_dt,
    dict_to_article,
    dict_to_follow,
    dict_to_summary,
    dict_to_tweet,
)


class ImportRepository:
    """将导入数据写入数据库。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── ScraperFollow ─────────────────────────────────────────

    def import_follows(
        self, items: list[dict[str, Any]], strategy: ConflictStrategy
    ) -> ImportStats:
        stats = ImportStats()
        for item in items:
            existing = self._session.execute(
                select(ScraperFollow).where(ScraperFollow.username == item["username"])
            ).scalar_one_or_none()

            if existing is None:
                params = dict_to_follow(item)
                self._session.add(ScraperFollow(**params))
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                params = dict_to_follow(item)
                for key, val in params.items():
                    if key != "username":
                        setattr(existing, key, val)
                stats.updated += 1
            elif strategy == ConflictStrategy.merge:
                # merge: 取较新的 added_at
                import_added_at = _iso_to_naive_dt(item.get("added_at"))
                if import_added_at and existing.added_at and import_added_at > existing.added_at:
                    params = dict_to_follow(item)
                    for key, val in params.items():
                        if key != "username":
                            setattr(existing, key, val)
                    stats.updated += 1
                else:
                    stats.skipped += 1
        return stats

    # ── Tweets ────────────────────────────────────────────────

    def import_tweets(self, items: list[dict[str, Any]], strategy: ConflictStrategy) -> ImportStats:
        stats = ImportStats()
        for item in items:
            existing = self._session.execute(
                select(TweetOrm).where(TweetOrm.tweet_id == item["tweet_id"])
            ).scalar_one_or_none()

            if existing is None:
                params = dict_to_tweet(item)
                self._session.add(TweetOrm(**params))
                stats.inserted += 1
            elif strategy == ConflictStrategy.merge:
                # merge 策略：tweets 不可变，永远跳过
                stats.skipped += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                params = dict_to_tweet(item)
                for key, val in params.items():
                    if key != "tweet_id":
                        setattr(existing, key, val)
                stats.updated += 1
        return stats

    # ── Summaries ─────────────────────────────────────────────

    def import_summaries(
        self, items: list[dict[str, Any]], strategy: ConflictStrategy
    ) -> ImportStats:
        stats = ImportStats()
        for item in items:
            existing = self._session.execute(
                select(SummaryOrm).where(SummaryOrm.summary_id == item["summary_id"])
            ).scalar_one_or_none()

            if existing is None:
                params = dict_to_summary(item)
                self._session.add(SummaryOrm(**params))
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.merge:
                # merge: 按 summary_id 去重，已存在则跳过
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                params = dict_to_summary(item)
                for key, val in params.items():
                    if key != "summary_id":
                        setattr(existing, key, val)
                stats.updated += 1
        return stats

    # ── Articles ──────────────────────────────────────────────

    def import_articles(
        self, items: list[dict[str, Any]], strategy: ConflictStrategy
    ) -> ImportStats:
        stats = ImportStats()
        for item in items:
            existing = self._session.execute(
                select(ArticleOrm).where(ArticleOrm.tweet_id == item["tweet_id"])
            ).scalar_one_or_none()

            if existing is None:
                params = dict_to_article(item)
                self._session.add(ArticleOrm(**params))
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                params = dict_to_article(item)
                for key, val in params.items():
                    if key != "tweet_id":
                        setattr(existing, key, val)
                stats.updated += 1
        return stats
