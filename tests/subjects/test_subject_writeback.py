from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.subjects.api import routes as subject_routes
from src.subjects.models import (
    SubjectHighlight,
    SubjectMatch,
    SubjectReviewSection,
)
from src.subjects.services.classifier import SubjectClassifier
from src.subjects.services.digest_service import SubjectDigestService
from src.subjects.services.review_service import ReviewConflictError, SubjectReviewService
from src.subjects.store import FileSubjectStore


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Skill 驱动议题",
        nl_description="用于验证外部技能写回",
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


@pytest.mark.asyncio
async def test_create_subject_opens_pending_and_set_pending_lists_jobs(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)

    pending = await repo.list_pending()

    assert pending == [
        {
            "subject_id": subject_id,
            "pending_classify": True,
            "pending_review": False,
        }
    ]

    await repo.set_pending(subject_id, classify=False, review=True)

    assert await repo.list_pending(subject_id) == [
        {
            "subject_id": subject_id,
            "pending_classify": False,
            "pending_review": True,
        }
    ]


@pytest.mark.asyncio
async def test_write_matches_validates_missing_and_closes_pending(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)

    async def fake_get_tweets_by_ids(tweet_ids: list[str]):
        missing = [tweet_id for tweet_id in tweet_ids if tweet_id == "ghost"]
        items = [{"tweet_id": tweet_id} for tweet_id in tweet_ids if tweet_id not in missing]
        return items, missing

    repo.get_tweets_by_ids = fake_get_tweets_by_ids  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="missing_ids"):
        await SubjectClassifier(repo).write_matches(subject_id=subject_id, tweet_ids=["ghost"])

    result = await SubjectClassifier(repo).write_matches(
        subject_id=subject_id,
        tweet_ids=["tw_1", "tw_2"],
        relevance=0.9,
        reason="相关",
    )

    assert result == {"written": 2, "subject_id": subject_id, "pending_classify": False}
    assert [match.tweet_id for match in await repo.list_matches(subject_id)] == ["tw_1", "tw_2"]
    assert (await repo.get_subject(subject_id)).pending_classify is False  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_digest_appends_month_jsonl_filters_interval_and_ignores_old_json(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject_id, tweet_id="in", matched_at=base + timedelta(minutes=5)
            ),
            SubjectMatch(
                subject_id=subject_id, tweet_id="out", matched_at=base - timedelta(hours=2)
            ),
        ]
    )

    old_hour = tmp_path / "subjects" / subject_id / "digests" / "2026-06-28-10.json"
    old_hour.parent.mkdir(parents=True, exist_ok=True)
    old_hour.write_text(json.dumps({"hour": "2026-06-28-10"}), encoding="utf-8")

    service = SubjectDigestService(repo)
    with pytest.raises(ValueError, match="4000"):
        await service.write_digest(
            subject_id=subject_id,
            interval_start=base,
            interval_end=base + timedelta(minutes=10),
            digest_text="x" * 4001,
        )
    with pytest.raises(ValueError, match="越出本区间"):
        await service.write_digest(
            subject_id=subject_id,
            interval_start=base,
            interval_end=base + timedelta(minutes=10),
            digest_text="合法正文",
            cited_tweet_ids=["out"],
        )

    await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(minutes=10),
        digest_text="第一版",
        highlights=[SubjectHighlight(point="要点", cited_tweet_ids=["in"])],
        cited_tweet_ids=["in"],
    )
    await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(minutes=10),
        digest_text="第二版",
        cited_tweet_ids=["in"],
    )

    shard = tmp_path / "subjects" / subject_id / "digests" / "2026-06.jsonl"
    assert len(shard.read_text(encoding="utf-8").splitlines()) == 2
    latest = await repo.get_digest(
        subject_id,
        start=base,
        end=base + timedelta(minutes=10),
    )
    assert latest is not None
    assert latest.digest_text == "第二版"
    assert latest.interval_start == base


@pytest.mark.asyncio
async def test_publish_window_matches_uses_created_at_and_feed_reuses_source(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="before",
                matched_at=base + timedelta(minutes=5),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="at_start",
                matched_at=base - timedelta(days=1),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="inside",
                matched_at=base + timedelta(days=1),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="at_end",
                matched_at=base + timedelta(minutes=10),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="missing",
                matched_at=base + timedelta(minutes=30),
            ),
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup(  # type: ignore[method-assign]
        {
            "before": base - timedelta(minutes=1),
            "at_start": base,
            "inside": base + timedelta(hours=1),
            "at_end": base + timedelta(hours=2),
        }
    )

    publish_matches = await repo._publish_window_matches(
        subject_id,
        start=base,
        end=base + timedelta(hours=2),
    )

    assert [match.tweet_id for match in publish_matches] == ["at_start", "inside"]
    assert publish_matches.skipped_no_publish_time_ids == ["missing"]

    publish_feed = await repo.get_subject_feed(
        subject_id,
        since=base,
        until=base + timedelta(hours=2),
        time_axis="publish",
    )
    assert [item["tweet_id"] for item in publish_feed["items"]] == ["at_start", "inside"]

    ingest_feed = await repo.get_subject_feed(
        subject_id,
        since=base,
        until=base + timedelta(hours=2),
    )
    assert [item["tweet_id"] for item in ingest_feed["items"]] == ["before", "at_end"]


@pytest.mark.asyncio
async def test_rest_feed_optional_time_axis_passes_through_to_store(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="publish_in",
                matched_at=base - timedelta(days=1),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="ingest_in",
                matched_at=base + timedelta(minutes=5),
            ),
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup(  # type: ignore[method-assign]
        {
            "publish_in": base + timedelta(minutes=5),
            "ingest_in": base - timedelta(days=1),
        }
    )

    with patch("src.subjects.api.routes.get_subject_repo", return_value=repo):
        publish_feed = await subject_routes.get_subject_feed(
            subject_id,
            since=base.isoformat(),
            until=(base + timedelta(hours=1)).isoformat(),
            time_axis="publish",
        )
        ingest_feed = await subject_routes.get_subject_feed(
            subject_id,
            since=base.isoformat(),
            until=(base + timedelta(hours=1)).isoformat(),
            time_axis=None,
        )

    assert [item["tweet_id"] for item in publish_feed["items"]] == ["publish_in"]
    assert [item["tweet_id"] for item in ingest_feed["items"]] == ["ingest_in"]


@pytest.mark.asyncio
async def test_write_digest_publish_axis_validates_citations_and_reports_skipped(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="publish_in",
                matched_at=base - timedelta(days=1),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="ingest_only",
                matched_at=base + timedelta(minutes=5),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="missing",
                matched_at=base + timedelta(minutes=6),
            ),
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup(  # type: ignore[method-assign]
        {
            "publish_in": base + timedelta(minutes=5),
            "ingest_only": base - timedelta(days=1),
        }
    )
    service = SubjectDigestService(repo)

    with pytest.raises(ValueError, match="越出本区间"):
        await service.write_digest(
            subject_id=subject_id,
            interval_start=base,
            interval_end=base + timedelta(hours=1),
            time_axis="publish",
            digest_text="发布时间轴正文",
            cited_tweet_ids=["ingest_only"],
        )

    result = await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(hours=1),
        time_axis="publish",
        digest_text="发布时间轴正文",
        highlights=[SubjectHighlight(point="发布轴命中", cited_tweet_ids=["publish_in"])],
        cited_tweet_ids=["publish_in"],
    )

    assert result["skipped_no_publish_time"] == 1
    assert result["skipped_no_publish_time_ids"] == ["missing"]
    latest = await repo.get_digest(
        subject_id,
        start=base,
        end=base + timedelta(hours=1),
    )
    assert latest is not None
    assert latest.time_axis == "publish"
    assert latest.tweet_count == 1

    ingest_result = await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(hours=1),
        digest_text="入库轴正文",
        cited_tweet_ids=["ingest_only"],
    )
    assert ingest_result["skipped_no_publish_time"] == 0


@pytest.mark.asyncio
async def test_write_digest_publish_empty_interval_allows_empty_citations(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    service = SubjectDigestService(repo)

    result = await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(hours=1),
        time_axis="publish",
        digest_text="空区间正文",
    )

    assert result["skipped_no_publish_time"] == 0
    latest = await repo.get_digest(
        subject_id,
        start=base,
        end=base + timedelta(hours=1),
    )
    assert latest is not None
    assert latest.tweet_count == 0

    with pytest.raises(ValueError, match="越出本区间"):
        await service.write_digest(
            subject_id=subject_id,
            interval_start=base,
            interval_end=base + timedelta(hours=1),
            time_axis="publish",
            digest_text="空区间引用越界",
            cited_tweet_ids=["ghost"],
        )


@pytest.mark.asyncio
async def test_review_write_success_conflict_and_per_section_validation(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    await repo.set_pending(subject_id, review=True)
    covered_until = datetime(2026, 6, 28, 12, tzinfo=UTC)

    service = SubjectReviewService(repo)
    result = await service.write_review(
        subject_id=subject_id,
        prev_version=0,
        sections=[SubjectReviewSection(title="总览", body="第一版综述")],
        covered_until=covered_until,
    )

    assert result == {"subject_id": subject_id, "version": 1}
    stored = await repo.get_review(subject_id)
    assert stored is not None
    assert stored.generated_by == "skill"
    assert stored.covered_until == covered_until
    assert (await repo.get_subject(subject_id)).pending_review is False  # type: ignore[union-attr]

    with pytest.raises(ReviewConflictError) as conflict:
        await service.write_review(
            subject_id=subject_id,
            prev_version=0,
            sections=[SubjectReviewSection(title="旧版", body="不应覆盖")],
            covered_until=covered_until + timedelta(hours=1),
        )
    assert conflict.value.latest_version == 1
    assert conflict.value.covered_until == covered_until
    assert (await repo.get_review(subject_id)).sections[0].body == "第一版综述"  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="第 2 段"):
        await service.write_review(
            subject_id=subject_id,
            prev_version=1,
            sections=[
                SubjectReviewSection(title="一", body="正常"),
                SubjectReviewSection(title="二", body="x" * 4001),
            ],
            covered_until=covered_until + timedelta(hours=1),
        )


def test_wipe_subject_artifacts_dry_run_and_confirm(tmp_path):
    data_root = tmp_path / "data"
    subject_dir = data_root / "subjects" / "s1"
    subject_dir.mkdir(parents=True)
    (data_root / "subjects" / "index.json").write_text(
        json.dumps({"subject_ids": ["s1"]}),
        encoding="utf-8",
    )
    (data_root / "subjects" / "s1.json").write_text(
        json.dumps(
            {
                "subject_id": "s1",
                "name": "议题",
                "nl_description": "描述",
                "keywords": [],
                "status": "active",
                "created_at": "2026-06-28T00:00:00Z",
                "updated_at": "2026-06-28T00:00:00Z",
                "pending_classify": True,
                "pending_review": True,
            }
        ),
        encoding="utf-8",
    )
    for rel in [
        "digests/2026-06.jsonl",
        "digests/2026-06-28-10.json",
        "review/latest.json",
        "matches/2026-06.jsonl",
    ]:
        path = subject_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    script = "scripts/wipe_subject_artifacts.py"
    env = {"XWATCHER_DATA_ROOT": str(data_root)}

    dry_run = subprocess.run(
        [sys.executable, script, "--subject-id", "s1"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "DRY-RUN" in dry_run.stdout
    assert (subject_dir / "digests" / "2026-06.jsonl").exists()

    applied = subprocess.run(
        [sys.executable, script, "--subject-id", "s1", "--confirm"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        input="YES\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Deleted files=3" in applied.stdout
    assert not (subject_dir / "digests" / "2026-06.jsonl").exists()
    assert not (subject_dir / "review" / "latest.json").exists()
    assert (subject_dir / "matches" / "2026-06.jsonl").exists()
    subject_doc = json.loads((data_root / "subjects" / "s1.json").read_text(encoding="utf-8"))
    assert subject_doc["pending_classify"] is False
    assert subject_doc["pending_review"] is False
