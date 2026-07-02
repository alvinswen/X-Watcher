from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.mcp.server import create_mcp_server
from src.subjects.models import SubjectDigest, SubjectMatch, SubjectReview, SubjectReviewSection
from src.subjects.services.eval_service import SubjectEvalService
from src.subjects.services.feedback_service import build_feedback_target_id
from src.subjects.store import FileSubjectStore


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Correction 议题",
        nl_description="验证人工更正率",
    )
    return subject.subject_id


def _tool_funcs():
    mcp = create_mcp_server()
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def _load_tool_result(raw: str) -> dict:
    return json.loads(raw)


async def _put_feedback(
    tools: dict,
    *,
    subject_id: str,
    target_type: str,
    target_id: str,
    verdict: str,
    authority: str = "human_correction",
    who: str = "human:alvin",
    supersedes: str | None = None,
) -> dict:
    return _load_tool_result(
        await tools["put_subject_feedback"](
            subject_id=subject_id,
            target_type=target_type,
            target_id=target_id,
            verdict=verdict,
            authority=authority,
            who=who,
            supersedes=supersedes,
        )
    )


@pytest.mark.asyncio
async def test_correction_rate_counts_current_human_corrections_after_supersedes(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    now = datetime(2026, 7, 8, 9, tzinfo=UTC)
    start = now - timedelta(days=1)
    match_ok = SubjectMatch(subject_id=subject_id, tweet_id="tw_ok", matched_at=start)
    match_overridden = SubjectMatch(
        subject_id=subject_id,
        tweet_id="tw_overridden",
        matched_at=start + timedelta(minutes=1),
    )
    old_match = SubjectMatch(
        subject_id=subject_id,
        tweet_id="tw_old",
        matched_at=now - timedelta(days=3),
    )
    await repo.upsert_matches([match_ok, match_overridden, old_match])
    digest = SubjectDigest(
        subject_id=subject_id,
        interval_start=start,
        interval_end=start + timedelta(hours=1),
        time_axis="publish",
        tweet_count=1,
        digest_text="digest",
        generated_at=start + timedelta(hours=2),
    )
    await repo.save_digest(digest)
    review = SubjectReview(
        subject_id=subject_id,
        version=1,
        sections=[SubjectReviewSection(title="总览", body="body")],
        generated_at=start + timedelta(hours=3),
        updated_at=start + timedelta(hours=3),
    )
    await repo.save_review(review)

    match_ok_target = build_feedback_target_id(
        "match",
        subject_id=subject_id,
        tweet_id=match_ok.tweet_id,
    )
    match_overridden_target = build_feedback_target_id(
        "match",
        subject_id=subject_id,
        tweet_id=match_overridden.tweet_id,
    )
    digest_target = build_feedback_target_id(
        "digest",
        subject_id=subject_id,
        interval_start=digest.interval_start,
        time_axis=digest.time_axis,
    )
    review_target = build_feedback_target_id("review", subject_id=subject_id, version=1)

    tools = _tool_funcs()
    with (
        patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo),
        patch("src.mcp.tools.subject_tools.require_scope", return_value=None),
    ):
        assert (
            await _put_feedback(
                tools,
                subject_id=subject_id,
                target_type="match",
                target_id=match_ok_target,
                verdict="reject",
            )
        )["success"]
        assert (
            await _put_feedback(
                tools,
                subject_id=subject_id,
                target_type="digest",
                target_id=digest_target,
                verdict="correct",
            )
        )["success"]
        assert (
            await _put_feedback(
                tools,
                subject_id=subject_id,
                target_type="review",
                target_id=review_target,
                verdict="accept",
            )
        )["success"]
        first = await _put_feedback(
            tools,
            subject_id=subject_id,
            target_type="match",
            target_id=match_overridden_target,
            verdict="reject",
        )
        assert first["success"]
        assert (
            await _put_feedback(
                tools,
                subject_id=subject_id,
                target_type="match",
                target_id=match_overridden_target,
                verdict="accept",
                authority="agent_selfeval",
                who="agent:judge",
                supersedes=first["data"]["id"],
            )
        )["success"]

    with patch("src.subjects.services.eval_service.utc_now", return_value=now):
        data, cycles = await SubjectEvalService(repo).get_correction_rate(
            subject_id=subject_id,
            window_days=2,
        )

    assert cycles == []
    assert data["by_type"]["match"] == {
        "produced": 2,
        "corrected": 1,
        "rate": 0.5,
        "not_applicable": False,
    }
    assert data["by_type"]["digest"]["corrected"] == 1
    assert data["by_type"]["review"] == {
        "produced": 1,
        "corrected": 0,
        "rate": 0,
        "not_applicable": False,
    }
    assert data["total"]["produced"] == 4
    assert data["total"]["corrected"] == 2


@pytest.mark.asyncio
async def test_correction_rate_zero_output_and_window_validation(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    now = datetime(2026, 7, 8, 9, tzinfo=UTC)
    service = SubjectEvalService(repo)

    with patch("src.subjects.services.eval_service.utc_now", return_value=now):
        data, cycles = await service.get_correction_rate(subject_id=subject_id, window_days=1)

    assert cycles == []
    assert data["total"] == {
        "produced": 0,
        "corrected": 0,
        "rate": None,
        "not_applicable": True,
    }

    for bad in [0, 366]:
        with pytest.raises(ValueError):
            await service.get_correction_rate(subject_id=subject_id, window_days=bad)
    with pytest.raises(ValueError, match="整数"):
        await service.get_correction_rate(subject_id=subject_id, window_days=1.5)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_correction_rate_tool_not_found(tmp_path):
    repo = FileSubjectStore(tmp_path)
    tools = _tool_funcs()

    with patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo):
        result = _load_tool_result(
            await tools["get_subject_correction_rate"](
                subject_id="sub_missing",
                window_days=7,
            )
        )

    assert result["success"] is False
    assert result["error_type"] == "not_found"
