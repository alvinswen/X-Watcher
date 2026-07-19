"""Storage path contract tests."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from src.storage.paths import (
    as_utc,
    author_shards,
    by_day_shard,
    canonical_shard,
    iter_by_day_shards,
    iter_canonical_shards,
    local_day_to_utc_window,
    subject_digest_shard,
    subject_doc,
    subject_eval_shard,
    subject_feedback_shard,
    subject_index,
    subject_match_shard,
    subject_provenance_doc,
    subject_review_doc,
    subject_review_history_doc,
    utc_dates_in_window,
)


def test_as_utc_normalizes_naive_and_aware_datetimes():
    naive = datetime(2026, 7, 19, 12, 30)
    aware = datetime(2026, 7, 19, 20, 30, tzinfo=timezone(timedelta(hours=8)))

    assert as_utc(naive) == datetime(2026, 7, 19, 12, 30, tzinfo=UTC)
    assert as_utc(aware) == datetime(2026, 7, 19, 12, 30, tzinfo=UTC)


def test_canonical_shard_lowercases_author_and_uses_utc_month(tmp_path):
    created_at = datetime(2026, 8, 1, 1, tzinfo=timezone(timedelta(hours=8)))

    assert canonical_shard(tmp_path, "Alice", created_at) == (
        tmp_path / "tweets" / "alice" / "2026-07.jsonl"
    )


def test_author_shards_returns_sorted_jsonl_files(tmp_path):
    base = tmp_path / "tweets" / "alice"
    base.mkdir(parents=True)
    (base / "2026-02.jsonl").touch()
    (base / "2026-01.jsonl").touch()
    (base / "ignored.txt").touch()

    assert author_shards(tmp_path, "ALICE") == [
        base / "2026-01.jsonl",
        base / "2026-02.jsonl",
    ]


def test_iter_canonical_shards_returns_sorted_two_level_files(tmp_path):
    first = tmp_path / "tweets" / "alice" / "2026-01.jsonl"
    second = tmp_path / "tweets" / "bob" / "2026-02.jsonl"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    second.touch()
    first.touch()

    assert iter_canonical_shards(tmp_path) == [first, second]


def test_by_day_shard_uses_iso_date(tmp_path):
    assert by_day_shard(tmp_path, date(2026, 7, 19)) == (
        tmp_path / "_views" / "by-day" / "2026-07-19.jsonl"
    )


def test_iter_by_day_shards_returns_sorted_jsonl_files(tmp_path):
    base = tmp_path / "_views" / "by-day"
    base.mkdir(parents=True)
    (base / "2026-07-20.jsonl").touch()
    (base / "2026-07-19.jsonl").touch()
    (base / "ignored.txt").touch()

    assert iter_by_day_shards(tmp_path) == [
        base / "2026-07-19.jsonl",
        base / "2026-07-20.jsonl",
    ]


@pytest.mark.parametrize(
    ("offset", "expected_start"),
    [
        (480, datetime(2026, 7, 19, 8, tzinfo=UTC)),
        (-300, datetime(2026, 7, 18, 19, tzinfo=UTC)),
    ],
)
def test_local_day_to_utc_window_is_half_open_and_24_hours(offset, expected_start):
    utc_start, utc_end = local_day_to_utc_window(date(2026, 7, 19), offset)

    assert utc_start == expected_start
    assert utc_end == expected_start + timedelta(days=1)
    assert utc_end - utc_start == timedelta(hours=24)


@pytest.mark.parametrize(
    ("utc_start", "utc_end", "expected"),
    [
        (
            datetime(2026, 7, 19, tzinfo=UTC),
            datetime(2026, 7, 20, tzinfo=UTC),
            [date(2026, 7, 19)],
        ),
        (
            datetime(2026, 7, 19, 23, tzinfo=UTC),
            datetime(2026, 7, 20, 1, tzinfo=UTC),
            [date(2026, 7, 19), date(2026, 7, 20)],
        ),
        (
            datetime(2026, 7, 19, 12, tzinfo=UTC),
            datetime(2026, 7, 20, tzinfo=UTC),
            [date(2026, 7, 19)],
        ),
    ],
)
def test_utc_dates_in_window_honors_midnight_end_boundary(
    utc_start,
    utc_end,
    expected,
):
    assert utc_dates_in_window(utc_start, utc_end) == expected


def test_subject_paths_match_current_layout(tmp_path):
    subject_id = "subject-1"
    when = datetime(2026, 7, 19, tzinfo=UTC)

    assert subject_doc(tmp_path, subject_id) == (tmp_path / "subjects" / f"{subject_id}.json")
    assert subject_index(tmp_path) == tmp_path / "subjects" / "index.json"
    assert subject_match_shard(tmp_path, subject_id, when) == (
        tmp_path / "subjects" / subject_id / "matches" / "2026-07.jsonl"
    )
    assert subject_digest_shard(tmp_path, subject_id, when) == (
        tmp_path / "subjects" / subject_id / "digests" / "2026-07.jsonl"
    )
    assert subject_feedback_shard(tmp_path, subject_id, when) == (
        tmp_path / "subjects" / subject_id / "feedback" / "2026-07.jsonl"
    )
    assert subject_eval_shard(tmp_path, subject_id, when) == (
        tmp_path / "subjects" / subject_id / "eval" / "2026-07.jsonl"
    )
    assert subject_review_doc(tmp_path, subject_id) == (
        tmp_path / "subjects" / subject_id / "review" / "latest.json"
    )
    assert subject_review_history_doc(tmp_path, subject_id, 3) == (
        tmp_path / "subjects" / subject_id / "review" / "history" / "3.json"
    )
    assert subject_provenance_doc(tmp_path, subject_id, "matches", "item-1") == (
        tmp_path / "subjects" / subject_id / "provenance" / "matches" / "item-1.json"
    )
