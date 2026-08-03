"""信源候选管理 REST 契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.preference.services.scraper_config_service import ScraperConfigService
from src.scraper.client import TwitterClient
from src.source_candidates.api import routes
from src.source_candidates.infrastructure.file_source_candidate_repository import (
    FileSourceCandidateStore,
)
from src.source_candidates.models import (
    CandidateAssessment,
    CandidateDecision,
    CandidateScores,
    CandidateStatus,
    CitationSignal,
    MiningSignal,
    SourceCandidate,
)
from src.source_candidates.services.candidate_service import CandidateService
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN


def _candidate(
    candidate_id: str = "candidatea",
    *,
    status: CandidateStatus = CandidateStatus.ASSESSED,
) -> SourceCandidate:
    first_discovered_at = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    last_mined_at = datetime(2026, 8, 2, 10, 45, tzinfo=UTC)
    candidate = SourceCandidate(
        candidate_id=candidate_id,
        username=candidate_id,
        platform_user_id="platform-42",
        status=status,
        mining=MiningSignal(
            citations={
                "source_a": CitationSignal(count=2, citing_tweet_ids=["tweet-1"]),
                "source_b": CitationSignal(count=1, citing_tweet_ids=["tweet-2"]),
            },
            citation_total=3,
            source_diversity=2,
            sample_citation_tweet_ids=["tweet-1", "tweet-missing"],
            subject_tags=["量化交易"],
            first_discovered_at=first_discovered_at,
            last_mined_at=last_mined_at,
        ),
        profile_snapshot={
            "display_name": "候选甲",
            "verified_type": "blue",
            "is_automated": False,
        },
        profile_fetched_at=datetime(2026, 8, 2, 11, 0, tzinfo=UTC),
    )
    if status == CandidateStatus.ASSESSED:
        candidate.assessment = CandidateAssessment(
            scores=CandidateScores(originality=8, difference=7, expertise=9),
            recommendation="建议批准。该账号发文以一手研究为主。",
            evidence_tweet_ids=["sample-1"],
            assessed_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            assessed_by="agent",
        )
    if status.is_terminal:
        verdict = "approve" if status == CandidateStatus.APPROVED else "reject"
        candidate.decision = CandidateDecision(
            verdict=verdict,
            decided_by="earlier-admin",
            decided_at=datetime(2026, 8, 3, 8, 0, tzinfo=UTC),
        )
    return candidate


def _service(tmp_path) -> tuple[CandidateService, FileSourceCandidateStore, FileFollowStore]:
    store = FileSourceCandidateStore(tmp_path)
    follow_store = FileFollowStore(tmp_path)
    service = CandidateService(
        store,
        follow_store,
        ScraperConfigService(follow_store),
        cast(TwitterClient, object()),
    )
    return service, store, follow_store


def _app(*, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router)
    if authenticated:
        app.dependency_overrides[get_current_admin_user] = lambda: BOOTSTRAP_ADMIN
    return app


async def _request(app: FastAPI, method: str, url: str, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_list_pending_returns_union_and_profile_projection(tmp_path, monkeypatch):
    service, store, _ = _service(tmp_path)
    await store.upsert_candidate(_candidate())
    await store.upsert_candidate(
        _candidate("candidateb", status=CandidateStatus.DISCOVERED)
    )
    await store.upsert_candidate(
        _candidate("candidatec", status=CandidateStatus.APPROVED)
    )
    monkeypatch.setattr(routes, "_service", lambda: service)

    response = await _request(
        _app(), "GET", "/api/admin/source-candidates?status=pending"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert {item["status"] for item in payload["candidates"]} == {
        "discovered",
        "assessed",
    }
    assert {
        "display_name",
        "verified_type",
        "is_automated",
    }.issubset(payload["candidates"][0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["page=0", "page_size=0", "page_size=101", "status=unknown"],
)
async def test_list_rejects_query_boundaries(query):
    response = await _request(
        _app(), "GET", f"/api/admin/source-candidates?{query}"
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_overflow_page_is_empty(tmp_path, monkeypatch):
    service, store, _ = _service(tmp_path)
    await store.upsert_candidate(_candidate())
    monkeypatch.setattr(routes, "_service", lambda: service)

    response = await _request(
        _app(), "GET", "/api/admin/source-candidates?page=2&page_size=1"
    )

    assert response.status_code == 200
    assert response.json()["candidates"] == []
    assert response.json()["total"] == 1


class _SubjectRepo:
    async def get_tweet_cards_by_ids(self, tweet_ids: list[str]):
        assert tweet_ids == ["tweet-1", "tweet-missing"]
        return ([{"tweet_id": "tweet-1", "text": "样例正文"}], ["tweet-missing"])


@pytest.mark.asyncio
async def test_detail_aggregates_cards_and_missing_ids(tmp_path, monkeypatch):
    service, store, _ = _service(tmp_path)
    await store.upsert_candidate(_candidate())
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(routes, "default_subject_repo", lambda: _SubjectRepo())

    response = await _request(
        _app(), "GET", "/api/admin/source-candidates/candidatea"
    )

    assert response.status_code == 200
    assert response.json()["candidate"]["candidate_id"] == "candidatea"
    assert response.json()["sample_citation_tweets"] == [
        {"tweet_id": "tweet-1", "text": "样例正文"}
    ]
    assert response.json()["missing_citation_tweet_ids"] == ["tweet-missing"]


@pytest.mark.asyncio
async def test_detail_returns_404_for_missing_candidate(tmp_path, monkeypatch):
    service, _, _ = _service(tmp_path)
    monkeypatch.setattr(routes, "_service", lambda: service)

    response = await _request(
        _app(), "GET", "/api/admin/source-candidates/candidatea"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "候选不存在"


@pytest.mark.asyncio
async def test_review_approve_writes_follow_and_audits(tmp_path, monkeypatch):
    service, store, follow_store = _service(tmp_path)
    await store.upsert_candidate(_candidate())
    audit = Mock()
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(routes, "audit_log", audit)

    response = await _request(
        _app(),
        "POST",
        "/api/admin/source-candidates/candidatea/review",
        json={"decision": "approve", "brief_intro": "量化研究"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["follow_id"] is not None
    follow = await follow_store.get_follow_by_username("candidatea")
    assert follow is not None
    assert follow.brief_intro == "量化研究"
    assert "预审:建议批准" in follow.reason
    audit.assert_called_once()
    assert audit.call_args.kwargs["source"] == "api"
    assert audit.call_args.kwargs["user"] == BOOTSTRAP_ADMIN.name


@pytest.mark.asyncio
async def test_review_reject_writes_decision_without_follow(tmp_path, monkeypatch):
    service, store, follow_store = _service(tmp_path)
    await store.upsert_candidate(
        _candidate(status=CandidateStatus.DISCOVERED)
    )
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(routes, "audit_log", Mock())

    response = await _request(
        _app(),
        "POST",
        "/api/admin/source-candidates/candidatea/review",
        json={"decision": "reject", "reject_reason": "内容以转载为主"},
    )

    assert response.status_code == 200
    stored = await store.get_candidate("candidatea")
    assert stored is not None and stored.decision is not None
    assert stored.status == CandidateStatus.REJECTED
    assert stored.decision.reject_reason == "内容以转载为主"
    assert await follow_store.get_follow_by_username("candidatea") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"decision": "reject", "brief_intro": "不允许"}, 400),
        ({"decision": "approve", "reject_reason": "不允许"}, 400),
        ({"decision": "other"}, 422),
        ({"decision": "approve", "brief_intro": "x" * 51}, 422),
        ({"decision": "reject", "reject_reason": "x" * 501}, 422),
    ],
)
async def test_review_rejects_invalid_parameter_combinations(
    tmp_path, monkeypatch, payload, expected_status
):
    service, store, _ = _service(tmp_path)
    await store.upsert_candidate(_candidate())
    audit = Mock()
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(routes, "audit_log", audit)

    response = await _request(
        _app(),
        "POST",
        "/api/admin/source-candidates/candidatea/review",
        json=payload,
    )

    assert response.status_code == expected_status
    if expected_status == 400:
        assert audit.call_args.kwargs["result"] == "failure"
    else:
        audit.assert_not_called()


@pytest.mark.asyncio
async def test_review_terminal_conflict_returns_409_with_decision(tmp_path, monkeypatch):
    service, store, _ = _service(tmp_path)
    await store.upsert_candidate(
        _candidate(status=CandidateStatus.APPROVED)
    )
    audit = Mock()
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(routes, "audit_log", audit)

    response = await _request(
        _app(),
        "POST",
        "/api/admin/source-candidates/candidatea/review",
        json={"decision": "reject"},
    )

    assert response.status_code == 409
    assert "已是终态 approved" in response.json()["detail"]
    assert "earlier-admin" in response.json()["detail"]
    assert audit.call_args.kwargs["result"] == "failure"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("GET", "/api/admin/source-candidates", None),
        ("GET", "/api/admin/source-candidates/candidatea", None),
        (
            "POST",
            "/api/admin/source-candidates/candidatea/review",
            {"decision": "approve"},
        ),
    ],
)
async def test_all_candidate_endpoints_require_authentication(method, path, json):
    response = await _request(_app(authenticated=False), method, path, json=json)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("GET", "/api/admin/source-candidates", None),
        ("GET", "/api/admin/source-candidates/candidatea", None),
        (
            "POST",
            "/api/admin/source-candidates/candidatea/review",
            {"decision": "approve"},
        ),
    ],
)
async def test_all_candidate_endpoints_reject_non_admin(method, path, json):
    app = _app(authenticated=False)

    async def deny_non_admin():
        raise HTTPException(status_code=403, detail="需要管理员权限")

    app.dependency_overrides[get_current_admin_user] = deny_non_admin
    response = await _request(app, method, path, json=json)

    assert response.status_code == 403
