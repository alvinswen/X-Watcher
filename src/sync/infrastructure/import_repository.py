"""Import 数据写入仓库。

批量写入 + 冲突检测，Topics 嵌套 ID 重映射。
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import ScraperFollow, ScraperScheduleConfig
from src.scraper.infrastructure.article_models import ArticleOrm
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.sync.domain.models import ConflictStrategy, ImportStats
from src.sync.infrastructure.serializers import (
    _iso_to_dt,
    _iso_to_naive_dt,
    dict_to_article,
    dict_to_follow,
    dict_to_schedule_config,
    dict_to_summary,
    dict_to_tweet,
)
from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
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
                select(ScraperFollow).where(
                    ScraperFollow.username == item["username"]
                )
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

    # ── ScraperScheduleConfig ─────────────────────────────────

    def import_schedule_config(
        self, item: dict[str, Any] | None, strategy: ConflictStrategy
    ) -> ImportStats:
        stats = ImportStats()
        if item is None:
            return stats

        existing = self._session.execute(
            select(ScraperScheduleConfig).where(ScraperScheduleConfig.id == 1)
        ).scalar_one_or_none()

        params = dict_to_schedule_config(item)

        if existing is None:
            self._session.add(ScraperScheduleConfig(id=1, **params))
            stats.inserted += 1
        elif strategy == ConflictStrategy.skip:
            stats.skipped += 1
        else:
            # overwrite 和 merge 对 singleton 都是覆盖
            for key, val in params.items():
                setattr(existing, key, val)
            stats.updated += 1
        return stats

    # ── Tweets ────────────────────────────────────────────────

    def import_tweets(
        self, items: list[dict[str, Any]], strategy: ConflictStrategy
    ) -> ImportStats:
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
                select(SummaryOrm).where(
                    SummaryOrm.summary_id == item["summary_id"]
                )
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
                select(ArticleOrm).where(
                    ArticleOrm.tweet_id == item["tweet_id"]
                )
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

    # ── Topics（嵌套）─────────────────────────────────────────

    def import_topics(
        self, items: list[dict[str, Any]], strategy: ConflictStrategy
    ) -> ImportStats:
        stats = ImportStats()
        for item in items:
            name = item["name"]
            existing = self._session.execute(
                select(TopicOrm).where(TopicOrm.name == name)
            ).scalar_one_or_none()

            if existing is None:
                self._create_topic(item)
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                self._overwrite_topic(existing, item)
                stats.updated += 1
            elif strategy == ConflictStrategy.merge:
                self._merge_topic(existing, item)
                stats.updated += 1
        return stats

    def _create_topic(self, item: dict[str, Any]) -> TopicOrm:
        topic = TopicOrm(name=item["name"], description=item.get("description"))
        self._session.add(topic)
        self._session.flush()

        for username in item.get("accounts", []):
            self._session.add(
                TopicAccountOrm(topic_id=topic.id, username=username)
            )

        for task_data in item.get("summary_tasks", []):
            self._create_summary_task(topic.id, task_data)

        return topic

    def _overwrite_topic(self, existing: TopicOrm, item: dict[str, Any]) -> None:
        existing.description = item.get("description")

        # 清除并重建 accounts
        for acc in list(existing.accounts):
            self._session.delete(acc)
        self._session.flush()
        for username in item.get("accounts", []):
            self._session.add(
                TopicAccountOrm(topic_id=existing.id, username=username)
            )

        # 清除并重建 summary_tasks
        for task in list(existing.summary_tasks):
            if task.summary:
                self._session.delete(task.summary)
            self._session.delete(task)
        self._session.flush()
        for task_data in item.get("summary_tasks", []):
            self._create_summary_task(existing.id, task_data)

    def _merge_topic(self, existing: TopicOrm, item: dict[str, Any]) -> None:
        # 合并 accounts（取并集）
        existing_usernames = {a.username for a in existing.accounts}
        for username in item.get("accounts", []):
            if username not in existing_usernames:
                self._session.add(
                    TopicAccountOrm(topic_id=existing.id, username=username)
                )

        # merge 策略：不覆盖已有 summary_tasks（跳过）

    def _create_summary_task(
        self, topic_id: int, task_data: dict[str, Any]
    ) -> None:
        task = TopicSummaryTaskOrm(
            topic_id=topic_id,
            time_span_hours=task_data["time_span_hours"],
            deadline=_iso_to_naive_dt(task_data["deadline"]),
            custom_prompt=task_data.get("custom_prompt"),
            tz_offset=task_data.get("tz_offset", 0),
            status=task_data.get("status", "pending"),
            error_message=task_data.get("error_message"),
            created_at=_iso_to_naive_dt(task_data.get("created_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            started_at=_iso_to_naive_dt(task_data.get("started_at")),
            completed_at=_iso_to_naive_dt(task_data.get("completed_at")),
        )
        self._session.add(task)
        self._session.flush()

        summary_data = task_data.get("summary")
        if summary_data:
            self._session.add(
                TopicSummaryOrm(
                    task_id=task.id,
                    content=summary_data["content"],
                    llm_provider=summary_data["llm_provider"],
                    llm_model=summary_data["llm_model"],
                    prompt_tokens=summary_data.get("prompt_tokens", 0),
                    completion_tokens=summary_data.get("completion_tokens", 0),
                    total_tokens=summary_data.get("total_tokens", 0),
                    cost_usd=summary_data.get("cost_usd", 0.0),
                    tweet_count=summary_data.get("tweet_count", 0),
                    account_count=summary_data.get("account_count", 0),
                    created_at=_iso_to_naive_dt(summary_data.get("created_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
