"""信源候选管理 REST routes。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.shared.audit_log import audit_log
from src.source_candidates.api.schemas import (
    CandidateListResponse,
    CandidateReviewRequest,
    CandidateReviewResponse,
)
from src.source_candidates.models import CandidateStatus
from src.source_candidates.services.candidate_service import (
    CandidateInternalError,
    CandidateNotFoundError,
    CandidateService,
    CandidateValidationError,
)
from src.subjects.protocol import default_subject_repo
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

router = APIRouter(prefix="/api/admin/source-candidates", tags=["source-candidates"])

_PENDING_STATUSES = [CandidateStatus.DISCOVERED, CandidateStatus.ASSESSED]


def _service() -> CandidateService:
    """同构 MCP 候选服务工厂，按请求惰性构造。"""
    from src.data_layer.provider import get_follows_repo, get_source_candidate_repo
    from src.preference.services.scraper_config_service import ScraperConfigService
    from src.scraper.client import TwitterClient

    follow_store = get_follows_repo()
    return CandidateService(
        get_source_candidate_repo(),
        follow_store,
        ScraperConfigService(follow_store),
        TwitterClient(),
    )


@router.get("", response_model=CandidateListResponse)
async def list_source_candidates(
    status: str | None = Query(
        default=None, pattern="^(pending|discovered|assessed|approved|rejected)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    try:
        if status == "pending":
            return await _service().list_candidates(
                statuses=_PENDING_STATUSES,
                page=page,
                page_size=page_size,
                include_profile_fields=True,
            )
        parsed = CandidateStatus(status) if status is not None else None
        return await _service().list_candidates(
            status=parsed,
            page=page,
            page_size=page_size,
            include_profile_fields=True,
        )
    except CandidateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{candidate_id}")
async def get_source_candidate(
    candidate_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    try:
        data = await _service().list_candidates(candidate_id=candidate_id)
    except CandidateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    citation_ids = data["candidate"].get("mining", {}).get(
        "sample_citation_tweet_ids", []
    )
    cards, missing = await default_subject_repo().get_tweet_cards_by_ids(citation_ids)
    return {
        **data,
        "sample_citation_tweets": cards,
        "missing_citation_tweet_ids": missing,
    }


@router.post("/{candidate_id}/review", response_model=CandidateReviewResponse)
async def review_source_candidate(
    candidate_id: str,
    request: CandidateReviewRequest,
    admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "candidate_id": candidate_id,
        "decision": request.decision,
        "brief_intro": request.brief_intro,
        "reject_reason": request.reject_reason,
    }
    try:
        if request.decision == "reject" and request.brief_intro is not None:
            raise CandidateValidationError("brief_intro 仅在 approve 时有效")
        if request.decision == "approve" and request.reject_reason is not None:
            raise CandidateValidationError("reject_reason 仅在 reject 时有效")
        result = await _service().review(
            candidate_id=candidate_id,
            decision=request.decision,
            decided_by=admin.name,
            brief_intro=request.brief_intro,
            reject_reason=request.reject_reason,
        )
    except (CandidateValidationError, CandidateNotFoundError, CandidateInternalError) as exc:
        audit_log(
            "review_candidate",
            request.decision,
            params=params,
            result="failure",
            error=str(exc),
            source="api",
            user=admin.name,
        )
        if isinstance(exc, CandidateNotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, CandidateInternalError):
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        code = 409 if "已是终态" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    audit_log(
        "review_candidate",
        request.decision,
        params=params,
        source="api",
        user=admin.name,
    )
    return result
