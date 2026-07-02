from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.mcp.tools.subject_tools import _collect_provenance
from src.subjects.models import SubjectHighlight, SubjectMatch, SubjectReviewSection
from src.subjects.provenance import assemble_provenance, build_candidate_set_hash
from src.subjects.services.classifier import SubjectClassifier
from src.subjects.services.digest_service import SubjectDigestService
from src.subjects.services.review_service import SubjectReviewService
from src.subjects.store import FileSubjectStore

PROMPT_HASH = "a" * 64


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Provenance 议题",
        nl_description="验证 subject 派生物溯源",
    )
    return subject.subject_id


def _raw_provenance(
    candidate_ids: list[str],
    *,
    candidate_set_hash: str | None = None,
    playbook_id: str | None = "xw-test",
    playbook_version: str | None = "2026.07",
    prompt_hash: str | None = PROMPT_HASH,
    model_name: str | None = "gpt-test",
    model_version: str | None = "2026-07-01",
) -> dict:
    return {
        "playbook_id": playbook_id,
        "playbook_version": playbook_version,
        "prompt_hash": prompt_hash,
        "candidate_set_hash": candidate_set_hash or build_candidate_set_hash(candidate_ids),
        "candidate_ids": candidate_ids,
        "model_name": model_name,
        "model_version": model_version,
    }


def _fake_tweet_lookup(created_by_id: dict[str, datetime]):
    async def fake_get_tweets_by_ids(tweet_ids: list[str]):
        items = [
            {"tweet_id": tweet_id, "created_at": created_by_id[tweet_id]}
            for tweet_id in tweet_ids
            if tweet_id in created_by_id
        ]
        missing = [tweet_id for tweet_id in tweet_ids if tweet_id not in created_by_id]
        return items, missing

    return fake_get_tweets_by_ids


def _single_json(base: Path) -> Path:
    paths = sorted(base.glob("*.json"))
    assert len(paths) == 1
    return paths[0]


def test_candidate_set_hash_and_assemble_validation_and_thresholds():
    assert build_candidate_set_hash(["b", "", "a", "b"]) == build_candidate_set_hash(["a", "b"])

    generated_at = datetime(2026, 7, 1, 10, tzinfo=UTC)
    prov_200 = assemble_provenance(
        raw=_raw_provenance([f"tw_{index:03d}" for index in range(200)]),
        recomputed_ids=[f"tw_{index:03d}" for index in reversed(range(200))],
        generated_at=generated_at,
    )
    assert prov_200.candidate_ids == [f"tw_{index:03d}" for index in range(200)]
    assert prov_200.validator_version == "1.0"

    ids_201 = [f"tw_{index:03d}" for index in range(201)]
    prov_201 = assemble_provenance(
        raw=_raw_provenance(ids_201),
        recomputed_ids=ids_201,
        generated_at=generated_at,
    )
    assert prov_201.candidate_ids is None

    with pytest.raises(ValueError, match="playbook_id"):
        assemble_provenance(
            raw=_raw_provenance(["tw_1"], playbook_id=None),
            recomputed_ids=["tw_1"],
            generated_at=generated_at,
        )
    with pytest.raises(ValueError, match="prompt_hash"):
        assemble_provenance(
            raw=_raw_provenance(["tw_1"], prompt_hash="not-a-hash"),
            recomputed_ids=["tw_1"],
            generated_at=generated_at,
        )
    with pytest.raises(ValueError, match="系统按该产物口径重算得 2 条候选"):
        assemble_provenance(
            raw=_raw_provenance(["tw_1"]),
            recomputed_ids=["tw_1", "tw_2"],
            generated_at=generated_at,
        )


@pytest.mark.asyncio
async def test_write_matches_saves_batch_sidecar_and_rejects_mismatch(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    repo.get_tweets_by_ids = _fake_tweet_lookup(  # type: ignore[method-assign]
        {
            "tw_1": datetime(2026, 7, 1, 10, tzinfo=UTC),
            "tw_2": datetime(2026, 7, 1, 11, tzinfo=UTC),
        }
    )

    result = await SubjectClassifier(repo).write_matches(
        subject_id=subject_id,
        tweet_ids=["tw_2", "tw_1", "tw_2"],
        provenance=_raw_provenance(["tw_1", "tw_2"]),
    )

    expected_hash = build_candidate_set_hash(["tw_1", "tw_2"])
    assert result == {
        "written": 2,
        "subject_id": subject_id,
        "pending_classify": False,
        "provenance_written": True,
        "provenance_key": expected_hash,
    }
    stored = await repo.read_provenance(
        subject_id=subject_id,
        kind="matches",
        key=expected_hash,
    )
    assert stored is not None
    assert stored.candidate_set_hash == expected_hash
    assert stored.candidate_ids == ["tw_1", "tw_2"]

    other_subject_id = await _subject(repo)
    with pytest.raises(ValueError, match="候选集指纹不符"):
        await SubjectClassifier(repo).write_matches(
            subject_id=other_subject_id,
            tweet_ids=["tw_1", "tw_2"],
            provenance=_raw_provenance(["tw_1"]),
        )
    assert await repo.list_matches(other_subject_id) == []
    assert (await repo.get_subject(other_subject_id)).pending_classify is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_write_digest_recomputes_publish_and_ingest_and_uses_generated_key(tmp_path):
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
    repo.get_tweets_by_ids = _fake_tweet_lookup(  # type: ignore[method-assign]
        {
            "publish_in": base + timedelta(minutes=5),
            "ingest_in": base - timedelta(days=1),
        }
    )
    service = SubjectDigestService(repo)

    publish_result = await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(hours=1),
        time_axis="publish",
        digest_text="发布轴摘要",
        highlights=[SubjectHighlight(point="发布", cited_tweet_ids=["publish_in"])],
        cited_tweet_ids=["publish_in"],
        provenance=_raw_provenance(["publish_in"]),
    )
    assert publish_result["provenance_written"] is True

    sidecar_path = _single_json(tmp_path / "subjects" / subject_id / "provenance" / "digests")
    assert publish_result["provenance_key"] == sidecar_path.stem
    key_interval, key_axis, key_generated = sidecar_path.stem.split("_")
    assert key_interval == "20260628T100000Z"
    assert key_axis == "publish"

    stored = await repo.read_provenance(
        subject_id=subject_id,
        kind="digests",
        key=sidecar_path.stem,
    )
    latest = await repo.get_digest(
        subject_id,
        start=base,
        end=base + timedelta(hours=1),
    )
    assert stored is not None
    assert latest is not None
    assert key_generated == stored.generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    assert stored.generated_at == latest.generated_at
    assert stored.candidate_ids == ["publish_in"]

    with pytest.raises(ValueError, match="候选集指纹不符"):
        await service.write_digest(
            subject_id=subject_id,
            interval_start=base,
            interval_end=base + timedelta(hours=1),
            digest_text="入库轴摘要",
            cited_tweet_ids=["ingest_in"],
            provenance=_raw_provenance(["publish_in"]),
        )

    ingest_result = await service.write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(hours=1),
        digest_text="入库轴摘要",
        cited_tweet_ids=["ingest_in"],
        provenance=_raw_provenance(["ingest_in"], model_name=None, model_version=None),
    )
    assert ingest_result["provenance_written"] is True
    sidecars = sorted(
        (tmp_path / "subjects" / subject_id / "provenance" / "digests").glob("*.json")
    )
    assert len(sidecars) == 2
    ingest_key = [path.stem for path in sidecars if "_ingest_" in path.stem][0]
    ingest_prov = await repo.read_provenance(
        subject_id=subject_id,
        kind="digests",
        key=ingest_key,
    )
    assert ingest_prov is not None
    assert ingest_prov.model_name is None
    assert ingest_prov.model_version is None


@pytest.mark.asyncio
async def test_write_review_saves_version_sidecar_and_rejects_subset_hash(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(subject_id=subject_id, tweet_id="r1", matched_at=base),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="r2",
                matched_at=base + timedelta(minutes=1),
            ),
        ]
    )

    service = SubjectReviewService(repo)
    result = await service.write_review(
        subject_id=subject_id,
        prev_version=0,
        sections=[SubjectReviewSection(title="总览", body="第一版", cited_tweet_ids=["r1"])],
        covered_until=base + timedelta(hours=1),
        cited_tweet_ids=["r1"],
        provenance=_raw_provenance(["r1", "r2"]),
    )

    assert result == {
        "subject_id": subject_id,
        "version": 1,
        "provenance_written": True,
        "provenance_key": "1",
    }
    stored = await repo.read_provenance(subject_id=subject_id, kind="review", key="1")
    assert stored is not None
    assert stored.candidate_ids == ["r1", "r2"]
    assert (await repo.get_subject(subject_id)).pending_review is False  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="候选集指纹不符"):
        await service.write_review(
            subject_id=subject_id,
            prev_version=1,
            sections=[SubjectReviewSection(title="错误", body="子集不应过")],
            covered_until=base + timedelta(hours=2),
            provenance=_raw_provenance(["r1"]),
        )
    assert (await repo.get_review(subject_id)).version == 1  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_sidecar_io_failure_keeps_digest_record_and_returns_false(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 6, 28, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(subject_id=subject_id, tweet_id="tw_1", matched_at=base),
        ]
    )

    async def fail_save_provenance(**_kwargs):
        raise OSError("disk full")

    repo.save_provenance = fail_save_provenance  # type: ignore[method-assign]

    result = await SubjectDigestService(repo).write_digest(
        subject_id=subject_id,
        interval_start=base,
        interval_end=base + timedelta(hours=1),
        digest_text="摘要已落",
        cited_tweet_ids=["tw_1"],
        provenance=_raw_provenance(["tw_1"]),
    )

    assert result["provenance_written"] is False
    assert "provenance_key" not in result
    latest = await repo.get_digest(
        subject_id,
        start=base,
        end=base + timedelta(hours=1),
    )
    assert latest is not None
    assert latest.digest_text == "摘要已落"


def test_collect_provenance_keeps_empty_compatible_and_parses_candidate_ids():
    assert _collect_provenance(None, None, None, None, None, None, None) is None

    collected = _collect_provenance(
        "xw-digest",
        None,
        None,
        None,
        "tw_1, tw_2,,",
        None,
        None,
    )

    assert collected == {
        "playbook_id": "xw-digest",
        "playbook_version": None,
        "prompt_hash": None,
        "candidate_set_hash": None,
        "candidate_ids": ["tw_1", "tw_2"],
        "model_name": None,
        "model_version": None,
    }
