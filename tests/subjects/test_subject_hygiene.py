from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.mcp.server import create_mcp_server
from src.subjects.models import (
    Provenance,
    SubjectDigest,
    SubjectMatch,
    SubjectReview,
    SubjectReviewSection,
)
from src.subjects.provenance import build_digest_provenance_key
from src.subjects.services.hygiene_service import SubjectHygieneService
from src.subjects.store import FileSubjectStore

PROMPT_HASH = "b" * 64


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Hygiene 议题",
        nl_description="验证卫生体检",
    )
    return subject.subject_id


def _tool_funcs():
    mcp = create_mcp_server()
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def _load_tool_result(raw: str) -> dict:
    return json.loads(raw)


def _provenance(candidate_ids: list[str], generated_at: datetime) -> Provenance:
    return Provenance(
        playbook_id="xw-test",
        playbook_version="2026.07",
        prompt_hash=PROMPT_HASH,
        candidate_set_hash="c" * 64,
        candidate_ids=candidate_ids,
        generated_at=generated_at,
    )


def _author_lookup(author_by_id: dict[str, str | None]):
    async def fake_get_tweet_author_ids(tweet_ids: list[str]):
        wanted = list(dict.fromkeys(tweet_ids))
        return (
            {tweet_id: author_by_id[tweet_id] for tweet_id in wanted if tweet_id in author_by_id},
            [tweet_id for tweet_id in wanted if tweet_id not in author_by_id],
        )

    return fake_get_tweet_author_ids


@pytest.mark.asyncio
async def test_digest_hygiene_passes_and_ref_round_trips(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    start = datetime(2026, 7, 1, 0, tzinfo=UTC)
    digest = SubjectDigest(
        subject_id=subject_id,
        interval_start=start,
        interval_end=start + timedelta(hours=1),
        time_axis="publish",
        tweet_count=3,
        digest_text="a" * 40,
        cited_tweet_ids=["tw_1", "tw_2", "tw_3"],
        generated_at=start + timedelta(hours=2),
    )
    await repo.save_digest(digest)
    key = build_digest_provenance_key(digest.interval_start, digest.time_axis, digest.generated_at)
    await repo.save_provenance(
        subject_id=subject_id,
        kind="digests",
        key=key,
        provenance=_provenance(["tw_1", "tw_2", "tw_3"], digest.generated_at),
    )
    repo.get_tweet_author_ids = _author_lookup(  # type: ignore[method-assign]
        {"tw_1": "uid_a", "tw_2": "uid_b", "tw_3": "uid_b"}
    )

    result = await SubjectHygieneService(repo).run_check(
        subject_id=subject_id,
        target_type="digest",
        interval_start=start,
        time_axis="publish",
    )

    eval_record = result["eval"]
    assert eval_record["tier"] == "hygiene"
    assert eval_record["target_provenance_ref"] == key
    assert eval_record["hard_fail"] is False
    assert eval_record["failed_checks"] == []
    assert eval_record["warnings"] == []
    assert eval_record["scores"]["cited_valid_rate"] == 1
    assert eval_record["scores"]["coverage_rate"] == 1
    assert eval_record["scores"]["source_count"] == 2
    assert len(await repo.read_evals(subject_id)) == 1


@pytest.mark.asyncio
async def test_digest_hygiene_ab_latest_multiple_and_source_collapse(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    start = datetime(2026, 7, 1, 0, tzinfo=UTC)
    first = SubjectDigest(
        subject_id=subject_id,
        interval_start=start,
        interval_end=start + timedelta(hours=1),
        time_axis="ingest",
        tweet_count=3,
        digest_text="first digest",
        cited_tweet_ids=["a1", "a2", "a3"],
        generated_at=start + timedelta(hours=1),
    )
    second = first.model_copy(
        update={
            "digest_text": "second digest",
            "cited_tweet_ids": ["b1", "b2", "b3"],
            "generated_at": start + timedelta(hours=2),
        }
    )
    await repo.save_digest(first)
    await repo.save_digest(second)
    first_key = build_digest_provenance_key(
        first.interval_start, first.time_axis, first.generated_at
    )
    second_key = build_digest_provenance_key(
        second.interval_start,
        second.time_axis,
        second.generated_at,
    )
    await repo.save_provenance(
        subject_id=subject_id,
        kind="digests",
        key=first_key,
        provenance=_provenance(["a1", "a2", "a3"], first.generated_at),
    )
    await repo.save_provenance(
        subject_id=subject_id,
        kind="digests",
        key=second_key,
        provenance=_provenance(["b1", "b2", "b3"], second.generated_at),
    )
    repo.get_tweet_author_ids = _author_lookup(  # type: ignore[method-assign]
        {"b1": "uid_same", "b2": "uid_same", "b3": "uid_same"}
    )

    result = await SubjectHygieneService(repo).run_check(
        subject_id=subject_id,
        target_type="digest",
        interval_start=start,
        time_axis="ingest",
    )

    eval_record = result["eval"]
    assert result["located"]["candidates_in_coordinate"] == 2
    assert eval_record["target_provenance_ref"] == second_key
    assert eval_record["hard_fail"] is True
    assert eval_record["failed_checks"] == ["source_collapse"]
    assert "multiple_in_interval" in eval_record["warnings"]


@pytest.mark.asyncio
async def test_hygiene_warning_tokens_for_missing_and_empty_basis(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    start = datetime(2026, 7, 1, 0, tzinfo=UTC)
    digest = SubjectDigest(
        subject_id=subject_id,
        interval_start=start,
        interval_end=start + timedelta(hours=1),
        time_axis="ingest",
        tweet_count=3,
        digest_text="warning digest",
        cited_tweet_ids=["tw_ok", "tw_no_author", "tw_missing"],
        generated_at=start + timedelta(hours=1),
    )
    await repo.save_digest(digest)
    key = build_digest_provenance_key(digest.interval_start, digest.time_axis, digest.generated_at)
    await repo.save_provenance(
        subject_id=subject_id,
        kind="digests",
        key=key,
        provenance=_provenance(["tw_ok", "tw_no_author", "tw_missing"], digest.generated_at),
    )
    repo.get_tweet_author_ids = _author_lookup(  # type: ignore[method-assign]
        {"tw_ok": "uid_ok", "tw_no_author": None}
    )

    result = await SubjectHygieneService(repo).run_check(
        subject_id=subject_id,
        target_type="digest",
        interval_start=start,
        time_axis="ingest",
        generated_at=digest.generated_at,
    )
    warnings = set(result["eval"]["warnings"])
    assert {"cited_tweets_missing", "author_id_unresolved", "citations_below_min"} <= warnings
    assert result["eval"]["scores"]["missing_cited_count"] == 1
    assert result["eval"]["scores"]["missing_author_id_count"] == 1

    empty = digest.model_copy(
        update={
            "cited_tweet_ids": [],
            "generated_at": start + timedelta(hours=2),
        }
    )
    await repo.save_digest(empty)
    result = await SubjectHygieneService(repo).run_check(
        subject_id=subject_id,
        target_type="digest",
        interval_start=start,
        time_axis="ingest",
        generated_at=empty.generated_at,
    )
    warnings = set(result["eval"]["warnings"])
    assert {"no_provenance_doc", "basis_recomputed_now", "candidate_set_empty"} <= warnings
    assert "cited_valid_rate" not in result["eval"]["scores"]
    assert result["eval"]["target_provenance_ref"] is None


@pytest.mark.asyncio
async def test_review_hygiene_and_match_reject_tool(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    generated_at = datetime(2026, 7, 1, 3, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(subject_id=subject_id, tweet_id="r1", matched_at=generated_at),
            SubjectMatch(subject_id=subject_id, tweet_id="r2", matched_at=generated_at),
            SubjectMatch(subject_id=subject_id, tweet_id="r3", matched_at=generated_at),
        ]
    )
    review = SubjectReview(
        subject_id=subject_id,
        version=1,
        sections=[
            SubjectReviewSection(title="长段", body="x" * 4001, cited_tweet_ids=["r1"]),
            SubjectReviewSection(title="重复", body="重复内容" * 20, cited_tweet_ids=["r2", "r3"]),
        ],
        cited_tweet_ids=[],
        generated_at=generated_at,
        updated_at=generated_at,
    )
    await repo.save_review(review)
    await repo.save_provenance(
        subject_id=subject_id,
        kind="review",
        key="1",
        provenance=_provenance(["r1", "r2", "r3"], generated_at),
    )
    repo.get_tweet_author_ids = _author_lookup(  # type: ignore[method-assign]
        {"r1": "uid_a", "r2": "uid_b", "r3": "uid_c"}
    )

    result = await SubjectHygieneService(repo).run_check(
        subject_id=subject_id,
        target_type="review",
        version=1,
    )

    assert result["eval"]["target_provenance_ref"] == "1"
    assert result["eval"]["hard_fail"] is True
    assert result["eval"]["failed_checks"] == ["length_exceeded"]
    assert result["eval"]["scores"]["duplicate_rate"] > 0

    tools = _tool_funcs()
    with patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo):
        rejected = _load_tool_result(
            await tools["run_subject_hygiene_check"](
                subject_id=subject_id,
                target_type="match",
            )
        )

    assert rejected["success"] is False
    assert rejected["error_type"] == "validation"
    assert "get_subject_correction_rate" in rejected["error"]
