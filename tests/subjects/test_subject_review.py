from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.subjects.models import (
    SubjectReview,
    SubjectReviewSection,
    SubjectReviewTrend,
)
from src.subjects.services.review_service import SubjectReviewService
from src.subjects.store import FileSubjectStore


@pytest.mark.asyncio
async def test_get_review_payload_returns_none_for_missing_subject(tmp_path):
    repo = FileSubjectStore(tmp_path)

    assert await SubjectReviewService(repo).get_review_payload("subj_missing") is None


@pytest.mark.asyncio
async def test_get_review_payload_returns_empty_v0_for_subject_without_review(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="Review 议题",
        nl_description="用于验证 SubjectReview 读取空态",
    )

    payload = await SubjectReviewService(repo).get_review_payload(subject.subject_id)

    assert payload == {
        "subject_id": subject.subject_id,
        "version": 0,
        "sections": [],
        "trend": {"emerging": [], "fading": []},
        "cited_tweet_ids": [],
        "prev_version": None,
        "generated_at": None,
        "generated_by": None,
        "updated_at": None,
        "covered_until": None,
    }


@pytest.mark.asyncio
async def test_get_review_payload_reads_stored_review(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="Review 议题",
        nl_description="用于验证 SubjectReview 读取历史数据",
    )
    generated_at = datetime(2026, 6, 28, 10, 0, tzinfo=UTC)
    review = await repo.save_review(
        SubjectReview(
            subject_id=subject.subject_id,
            version=1,
            sections=[
                SubjectReviewSection(
                    title="已有分节",
                    body="已有历史综述正文。",
                    cited_tweet_ids=["tw_1"],
                )
            ],
            trend=SubjectReviewTrend(emerging=["新论点"], fading=[]),
            cited_tweet_ids=["tw_1"],
            prev_version=None,
            generated_at=generated_at,
            generated_by="llm",
            updated_at=generated_at,
            covered_until=generated_at,
        )
    )

    payload = await SubjectReviewService(repo).get_review_payload(subject.subject_id)

    assert payload == review.model_dump(mode="json")
