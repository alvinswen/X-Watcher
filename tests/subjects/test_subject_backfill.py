from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from src.scraper.task_registry import TaskRegistry, TaskStatus
from src.subjects.models import SubjectMatch
from src.subjects.services import backfill_service as backfill_module
from src.subjects.services.backfill_service import MAX_BACKFILL_TWEETS, SubjectBackfillService
from src.subjects.store import FileSubjectStore
from src.summarization.services.summarization_queue import SummarizationPriority


@dataclass
class _BackfillTweet:
    tweet_id: str
    created_at: datetime


class _QueueRecorder:
    def __init__(self) -> None:
        self.started = False
        self.calls: list[dict] = []

    async def start(self) -> None:
        self.started = True

    async def enqueue(self, tweet_ids: list[str], **kwargs) -> str:
        self.calls.append({"tweet_ids": tweet_ids, **kwargs})
        return str(kwargs.get("task_id") or "task-id")


class _FailingQueue(_QueueRecorder):
    async def enqueue(self, tweet_ids: list[str], **kwargs) -> str:
        await super().enqueue(tweet_ids, **kwargs)
        raise RuntimeError("LLM 连续失败")


def _patch_queue(monkeypatch: pytest.MonkeyPatch, queue: _QueueRecorder) -> None:
    monkeypatch.setattr(
        backfill_module.SummarizationQueue,
        "get_instance",
        classmethod(lambda cls: queue),
    )


@pytest.mark.asyncio
async def test_tc_summ_080_081_backfill_enqueues_newest_low_priority_and_logs_cap(
    tmp_path,
    monkeypatch,
    caplog,
):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="回填议题",
        nl_description="用于验证回填排序、限流和队列优先级",
    )
    base = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    tweets = [
        _BackfillTweet(tweet_id=f"tw_{idx:04d}", created_at=base + timedelta(seconds=idx))
        for idx in range(MAX_BACKFILL_TWEETS + 2)
    ]

    async def fake_get_all_tweets(self):  # noqa: ANN001
        return list(tweets)

    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    monkeypatch.setattr(FileTweetStore, "get_all_tweets", fake_get_all_tweets)
    queue = _QueueRecorder()
    _patch_queue(monkeypatch, queue)

    registry = TaskRegistry.get_instance()
    task_id = registry.create_task(
        "subject backfill test",
        metadata={"subject_id": subject.subject_id, "task_type": "subject_backfill"},
    )
    caplog.set_level("WARNING", logger=backfill_module.logger.name)

    try:
        await SubjectBackfillService(repo)._enqueue_backfill(task_id, subject.subject_id)
        status = registry.get_task_status(task_id)
    finally:
        registry.delete_task(task_id)

    assert status is not None
    assert status["status"] == TaskStatus.RUNNING
    assert queue.started is True
    assert len(queue.calls) == 1

    call = queue.calls[0]
    enqueued_ids = call["tweet_ids"]
    assert len(enqueued_ids) == MAX_BACKFILL_TWEETS
    assert enqueued_ids[0] == "tw_5001"
    assert enqueued_ids[-1] == "tw_0002"
    assert "tw_0001" not in enqueued_ids
    assert "tw_0000" not in enqueued_ids
    assert call["force_refresh"] is True
    assert call["source"] == "subject_backfill"
    assert call["priority"] == SummarizationPriority.LOW
    assert call["task_id"] == task_id
    assert "超过单次上限" in caplog.text
    assert "跳过 2 条" in caplog.text


@pytest.mark.asyncio
async def test_tc_summ_082_backfill_failure_marks_task_failed_and_preserves_matches(
    tmp_path,
    monkeypatch,
):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="失败回填议题",
        nl_description="用于验证失败隔离和已写 match 不回滚",
    )
    matched_at = datetime(2026, 6, 27, 13, 0, tzinfo=timezone.utc)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="tw_existing",
                matched_at=matched_at,
                reason="已经写入的 match",
            )
        ]
    )

    async def fake_get_all_tweets(self):  # noqa: ANN001
        return [_BackfillTweet(tweet_id="tw_new", created_at=matched_at)]

    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    monkeypatch.setattr(FileTweetStore, "get_all_tweets", fake_get_all_tweets)
    _patch_queue(monkeypatch, _FailingQueue())

    registry = TaskRegistry.get_instance()
    task_id = registry.create_task(
        "subject backfill failure test",
        metadata={"subject_id": subject.subject_id, "task_type": "subject_backfill"},
    )

    try:
        await SubjectBackfillService(repo)._enqueue_backfill(task_id, subject.subject_id)
        status = registry.get_task_status(task_id)
    finally:
        registry.delete_task(task_id)

    assert status is not None
    assert status["status"] == TaskStatus.FAILED
    assert "LLM 连续失败" in status["error"]
    matches = await repo.list_matches(subject.subject_id)
    assert [match.tweet_id for match in matches] == ["tw_existing"]
