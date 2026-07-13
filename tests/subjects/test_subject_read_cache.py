"""Subject 全量 tweet/summary 读缓存接线回归。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.subjects.store import FileSubjectStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore


def _tweet(tweet_id: str, author: str) -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=f"tweet {tweet_id}",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        author_username=author,
        author_user_id=f"user-{author}",
    )


def _summary(tweet_id: str, text: str) -> SummaryRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SummaryRecord(
        summary_id=f"summary-{tweet_id}",
        tweet_id=tweet_id,
        summary_text=text,
        model_provider="test",
        model_name="test",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0,
        content_hash=f"hash-{tweet_id}",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_subject_reads_see_tweet_and_summary_writes_immediately(tmp_path: Path) -> None:
    tweets = FileTweetStore(tmp_path)
    summaries = FileSummaryStore(tmp_path)
    subjects = FileSubjectStore(tmp_path)
    await tweets.save_tweets([_tweet("t1", "alice")], early_stop_threshold=0)

    first, missing = await subjects.get_tweets_by_ids(["t1", "missing"])
    assert first[0]["summary"] is None
    assert missing == ["missing"]

    await summaries.seed([_summary("t1", "new summary with longer bytes")])
    await tweets.save_tweets([_tweet("t2", "bob")], early_stop_threshold=0)

    second, missing = await subjects.get_tweets_by_ids(["t1", "t2"])
    author_ids, author_missing = await subjects.get_tweet_author_ids(["t1", "t2", "missing"])

    assert {item["tweet_id"] for item in second} == {"t1", "t2"}
    assert second[0]["summary"] == "new summary with longer bytes"
    assert missing == []
    assert author_ids == {"t1": "user-alice", "t2": "user-bob"}
    assert author_missing == ["missing"]


@pytest.mark.asyncio
async def test_subject_repeated_reads_do_not_pollute_shared_maps(tmp_path: Path) -> None:
    await FileTweetStore(tmp_path).save_tweets([_tweet("t1", "alice")], early_stop_threshold=0)
    await FileSummaryStore(tmp_path).seed([_summary("t1", "summary")])
    subjects = FileSubjectStore(tmp_path)

    first = await subjects.get_tweets_by_ids(["t1", "t1", ""])
    second = await subjects.get_tweets_by_ids(["t1"])

    assert first == second
