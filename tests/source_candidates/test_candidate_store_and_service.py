"""信源候选盘面与状态服务测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.preference.services.scraper_config_service import ScraperConfigService
from src.scraper.client import TwitterClient
from src.source_candidates.infrastructure.file_source_candidate_repository import (
    FileSourceCandidateStore,
)
from src.source_candidates.models import (
    CandidateSample,
    CandidateStatus,
    CitationSignal,
    MiningSignal,
    SourceCandidate,
)
from src.source_candidates.services.candidate_service import (
    CandidateInternalError,
    CandidateService,
    CandidateValidationError,
)
from src.storage.paths import source_candidate_index


def _candidate(candidate_id="candidatea"):
    now = datetime.now(UTC)
    return SourceCandidate(
        candidate_id=candidate_id,
        username=candidate_id,
        mining=MiningSignal(
            citations={
                "source_a": CitationSignal(count=2, citing_tweet_ids=["1", "2"]),
                "source_b": CitationSignal(count=1, citing_tweet_ids=["3"]),
            },
            citation_total=3,
            source_diversity=2,
            sample_citation_tweet_ids=["1", "2", "3"],
            first_discovered_at=now,
            last_mined_at=now,
        ),
    )


def _service(store, follow_store):
    return CandidateService(
        store,
        follow_store,
        ScraperConfigService(follow_store),
        cast(TwitterClient, object()),
    )


@pytest.mark.asyncio
async def test_index_rebuilds_from_candidate_docs(tmp_path):
    store = FileSourceCandidateStore(tmp_path)
    candidate = _candidate()
    await store.upsert_candidate(candidate)
    source_candidate_index(tmp_path).write_text("{bad json", encoding="utf-8")

    items = await store.list_candidates()

    assert [item.candidate_id for item in items] == [candidate.candidate_id]
    assert (await store.all_index_entries())[candidate.candidate_id]["citation_total"] == 3


@pytest.mark.asyncio
async def test_assessment_evidence_is_fail_closed_and_whole_replacement(tmp_path):
    store = FileSourceCandidateStore(tmp_path)
    follow_store = FileFollowStore(tmp_path)
    candidate = _candidate()
    candidate.sample = CandidateSample(
        tweets=[{"tweet_id": "sample-1"}],
        fetched_at=datetime.now(UTC),
    )
    await store.upsert_candidate(candidate)
    service = _service(store, follow_store)

    with pytest.raises(CandidateValidationError, match="不含该编号"):
        await service.submit_assessment(
            candidate_id=candidate.candidate_id,
            originality_score=7,
            difference_score=6,
            expertise_score=8,
            recommendation="建议批准",
            evidence_tweet_ids=["1"],
            assessed_by="agent",
        )

    first = await service.submit_assessment(
        candidate_id=candidate.candidate_id,
        originality_score=7,
        difference_score=6,
        expertise_score=8,
        recommendation="建议批准",
        evidence_tweet_ids=["sample-1"],
        assessed_by="agent-1",
    )
    second = await service.submit_assessment(
        candidate_id=candidate.candidate_id,
        originality_score=2,
        difference_score=3,
        expertise_score=4,
        recommendation="存疑",
        evidence_tweet_ids=["sample-1"],
        assessed_by="agent-2",
    )

    assert first["status"] == second["status"] == "assessed"
    stored = await store.get_candidate(candidate.candidate_id)
    assert stored is not None and stored.assessment is not None
    assert stored.assessment.scores.originality == 2
    assert stored.assessment.assessed_by == "agent-2"


class _FailOnceStore(FileSourceCandidateStore):
    def __init__(self, data_root):
        super().__init__(data_root)
        self.fail_next = False

    async def upsert_candidate(self, candidate):
        if self.fail_next:
            self.fail_next = False
            raise OSError("injected candidate write failure")
        await super().upsert_candidate(candidate)


class _CompensationFailFollowStore(FileFollowStore):
    async def deactivate_follow(self, username):
        raise OSError("injected compensation failure")


@pytest.mark.asyncio
async def test_approve_retry_converges_after_candidate_and_compensation_failure(tmp_path):
    store = _FailOnceStore(tmp_path)
    follow_store = _CompensationFailFollowStore(tmp_path)
    await store.upsert_candidate(_candidate())
    service = _service(store, follow_store)
    store.fail_next = True

    with pytest.raises(CandidateInternalError, match="补偿失败"):
        await service.review(
            candidate_id="candidatea",
            decision="approve",
            decided_by="pm",
        )

    legacy = await follow_store.get_follow_by_username("candidatea")
    assert legacy is not None and legacy.is_active
    assert legacy.added_by == "candidate_review:pm"
    stored = await store.get_candidate("candidatea")
    assert stored is not None and stored.status.value == "discovered"

    result = await service.review(
        candidate_id="candidatea",
        decision="approve",
        decided_by="pm",
    )

    assert result["status"] == "approved"
    assert len(await follow_store.get_all_follows()) == 1
    stored = await store.get_candidate("candidatea")
    assert stored is not None and stored.decision is not None
    assert stored.decision.follow_id == legacy.id


def _fixed_candidate(
    candidate_id: str,
    *,
    status: CandidateStatus = CandidateStatus.DISCOVERED,
) -> SourceCandidate:
    first_discovered_at = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    last_mined_at = datetime(2026, 8, 2, 10, 45, tzinfo=UTC)
    return SourceCandidate(
        candidate_id=candidate_id,
        username=candidate_id,
        platform_user_id="platform-42",
        status=status,
        mining=MiningSignal(
            citations={
                "source_a": CitationSignal(count=2, citing_tweet_ids=["tweet-1"]),
            },
            citation_total=2,
            source_diversity=1,
            sample_citation_tweet_ids=["tweet-1"],
            subject_tags=["量化交易"],
            first_discovered_at=first_discovered_at,
            last_mined_at=last_mined_at,
        ),
        profile_snapshot={
            "display_name": "固定档案",
            "verified_type": "blue",
            "is_automated": False,
        },
    )


@pytest.mark.asyncio
async def test_list_candidates_preserves_frozen_summary_by_default(tmp_path):
    store = FileSourceCandidateStore(tmp_path)
    follow_store = FileFollowStore(tmp_path)
    candidate = _fixed_candidate("candidatea")
    await store.upsert_candidate(candidate)

    result = await _service(store, follow_store).list_candidates()

    assert result["candidates"][0] == {
        "candidate_id": "candidatea",
        "username": "candidatea",
        "platform_user_id": "platform-42",
        "status": "discovered",
        "citation_total": 2,
        "source_diversity": 1,
        "subject_tags": ["量化交易"],
        "first_discovered_at": "2026-08-01T09:30:00+00:00",
        "last_mined_at": "2026-08-02T10:45:00+00:00",
        "sample_fetched_at": None,
        "assessed_at": None,
        "decided_at": None,
    }


@pytest.mark.asyncio
async def test_list_candidates_projects_exactly_three_profile_fields(tmp_path):
    store = FileSourceCandidateStore(tmp_path)
    follow_store = FileFollowStore(tmp_path)
    candidate = _fixed_candidate("candidatea")
    await store.upsert_candidate(candidate)
    service = _service(store, follow_store)

    default_summary = (await service.list_candidates())["candidates"][0]
    projected_summary = (
        await service.list_candidates(include_profile_fields=True)
    )["candidates"][0]

    assert set(projected_summary) - set(default_summary) == {
        "display_name",
        "verified_type",
        "is_automated",
    }
    assert projected_summary == {
        **default_summary,
        "display_name": "固定档案",
        "verified_type": "blue",
        "is_automated": False,
    }


@pytest.mark.asyncio
async def test_list_candidates_supports_status_union_and_rejects_mixed_filters(tmp_path):
    store = FileSourceCandidateStore(tmp_path)
    follow_store = FileFollowStore(tmp_path)
    await store.upsert_candidate(_fixed_candidate("candidatea"))
    await store.upsert_candidate(
        _fixed_candidate("candidateb", status=CandidateStatus.ASSESSED)
    )
    await store.upsert_candidate(
        _fixed_candidate("candidatec", status=CandidateStatus.APPROVED)
    )
    service = _service(store, follow_store)

    result = await service.list_candidates(
        statuses=[CandidateStatus.DISCOVERED, CandidateStatus.ASSESSED],
        page=1,
        page_size=1,
    )

    assert result["total"] == 2
    assert result["count"] == 1
    assert result["candidates"][0]["status"] in {"discovered", "assessed"}
    with pytest.raises(CandidateValidationError, match="不能同时给定"):
        await service.list_candidates(
            status=CandidateStatus.DISCOVERED,
            statuses=[CandidateStatus.ASSESSED],
        )
