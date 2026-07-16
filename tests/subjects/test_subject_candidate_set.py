from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.subjects.models import SubjectMatch
from src.subjects.provenance import build_candidate_set_hash
from src.subjects.store import FileSubjectStore

EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Candidate Set 议题",
        nl_description="验证候选集三口径",
    )
    return subject.subject_id


def _tweet_lookup(created_by_id: dict[str, datetime]):
    async def fake_get_tweets_by_ids(tweet_ids: list[str]):
        items = [
            {"tweet_id": tweet_id, "created_at": created_by_id[tweet_id]}
            for tweet_id in tweet_ids
            if tweet_id in created_by_id
        ]
        missing = [tweet_id for tweet_id in tweet_ids if tweet_id not in created_by_id]
        return items, missing

    return fake_get_tweets_by_ids


def _candidate_ids(matches: list[SubjectMatch]) -> list[str]:
    return sorted({match.tweet_id for match in matches if match.tweet_id})


@pytest.mark.asyncio
async def test_store_candidate_set_axes_share_hash_source(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="pub_a",
                matched_at=base - timedelta(days=1),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="pub_b",
                matched_at=base + timedelta(minutes=5),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="ingest_only",
                matched_at=base + timedelta(minutes=15),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="missing_publish",
                matched_at=base + timedelta(minutes=20),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="at_end",
                matched_at=base + timedelta(hours=1),
            ),
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup(  # type: ignore[method-assign]
        {
            "pub_a": base + timedelta(minutes=5),
            "pub_b": base + timedelta(minutes=10),
            "ingest_only": base - timedelta(hours=1),
            "at_end": base + timedelta(hours=2),
        }
    )

    publish_matches = await repo.publish_window_matches(
        subject_id,
        start=base,
        end=base + timedelta(hours=1),
    )
    assert hasattr(publish_matches, "skipped_no_publish_time_ids")
    assert publish_matches.skipped_no_publish_time_ids == ["missing_publish"]
    publish_ids = _candidate_ids(publish_matches)
    assert publish_ids == ["pub_a", "pub_b"]

    ingest_matches = await repo.list_matches(
        subject_id,
        since=base,
        until=base + timedelta(hours=1),
    )
    ingest_ids = _candidate_ids(ingest_matches)
    assert ingest_ids == ["ingest_only", "missing_publish", "pub_b"]

    review_ids = _candidate_ids(await repo.list_matches(subject_id))
    assert review_ids == ["at_end", "ingest_only", "missing_publish", "pub_a", "pub_b"]

    for candidate_ids in (publish_ids, ingest_ids, review_ids):
        assert build_candidate_set_hash(candidate_ids) == build_candidate_set_hash(
            list(reversed(candidate_ids))
        )


@pytest.mark.asyncio
async def test_empty_candidate_sets_keep_deterministic_hash_and_skipped_count(tmp_path):
    repo = FileSubjectStore(tmp_path)
    empty_subject_id = await _subject(repo)

    assert _candidate_ids(await repo.list_matches(empty_subject_id)) == []
    assert build_candidate_set_hash([]) == EMPTY_HASH

    skipped_subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=skipped_subject_id,
                tweet_id="no_created_at",
                matched_at=base + timedelta(minutes=5),
            )
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup({})  # type: ignore[method-assign]

    publish_matches = await repo.publish_window_matches(
        skipped_subject_id,
        start=base,
        end=base + timedelta(hours=1),
    )

    assert _candidate_ids(publish_matches) == []
    assert publish_matches.skipped_no_publish_time_ids == ["no_created_at"]
    assert build_candidate_set_hash(_candidate_ids(publish_matches)) == EMPTY_HASH
