"""Subject 新建回填任务。"""

from __future__ import annotations

import asyncio
import logging

from src.data_layer.provider import get_subject_repo
from src.scraper.task_registry import TaskRegistry, TaskStatus
from src.summarization.services.summarization_queue import (
    SummarizationPriority,
    SummarizationQueue,
)

logger = logging.getLogger(__name__)

MAX_BACKFILL_TWEETS = 5000


class SubjectBackfillService:
    def __init__(self, repo=None) -> None:
        self._repo = repo if repo is not None else get_subject_repo()
        self._registry = TaskRegistry.get_instance()

    async def start_backfill(self, subject_id: str) -> str:
        subject = await self._repo.get_subject(subject_id)
        task_id = self._registry.create_task(
            task_name=f"议题回填 {subject.name if subject else subject_id}",
            metadata={"subject_id": subject_id, "task_type": "subject_backfill"},
        )
        await self._repo.set_backfill_task(subject_id, task_id)
        asyncio.create_task(self._enqueue_backfill(task_id, subject_id), name=f"subject-backfill-{subject_id}")
        return task_id

    async def _enqueue_backfill(self, task_id: str, subject_id: str) -> None:
        try:
            from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

            subject = await self._repo.get_subject(subject_id)
            if subject is None:
                self._registry.update_task_status(task_id, TaskStatus.FAILED, error="议题不存在")
                return

            self._registry.update_task_status(task_id, TaskStatus.RUNNING)
            tweets = await FileTweetStore(self._repo._root).get_all_tweets()  # noqa: SLF001
            tweets.sort(key=lambda item: item.created_at, reverse=True)
            total_candidates = len(tweets)
            selected = tweets[:MAX_BACKFILL_TWEETS]
            if total_candidates > MAX_BACKFILL_TWEETS:
                logger.warning(
                    "议题回填超过单次上限，仅处理前 %s 条，跳过 %s 条: subject_id=%s",
                    MAX_BACKFILL_TWEETS,
                    total_candidates - MAX_BACKFILL_TWEETS,
                    subject_id,
                )

            if not selected:
                self._registry.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    result={"subject_id": subject_id, "tweet_count": 0},
                )
                return

            queue = SummarizationQueue.get_instance()
            await queue.start()
            await queue.enqueue(
                [tweet.tweet_id for tweet in selected],
                force_refresh=True,
                source="subject_backfill",
                priority=SummarizationPriority.LOW,
                task_id=task_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("议题回填入队失败: subject_id=%s", subject_id)
            self._registry.update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
