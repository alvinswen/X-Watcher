"""Subject admin REST routes。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.subjects.api.schemas import (
    SubjectCreateRequest,
    SubjectCreateResponse,
    SubjectResponse,
    SubjectReviewRefreshResponse,
    SubjectReviewResponse,
    SubjectUpdateRequest,
)
from src.subjects.constants import (
    MAX_ACTIVE_SUBJECTS,
    REVIEW_MIGRATED_MESSAGE,
    REVIEW_PENDING_MESSAGE,
    SUBJECT_NOT_FOUND,
)
from src.subjects.models import Subject, SubjectDigest, SubjectStatus
from src.subjects.protocol import default_subject_repo
from src.subjects.services.review_service import SubjectReviewService
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

router = APIRouter(prefix="/api/admin/subjects", tags=["subjects"])


async def _to_response(subject: Subject) -> SubjectResponse:
    repo = default_subject_repo()
    return SubjectResponse(
        subject_id=subject.subject_id,
        name=subject.name,
        nl_description=subject.nl_description,
        keywords=subject.keywords,
        status=subject.status.value,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
        last_updated_at=subject.last_updated_at,
        match_count=await repo.count_matches(subject.subject_id),
    )


def _digest_public(digest: SubjectDigest) -> dict[str, Any]:
    return digest.model_dump(mode="json", exclude={"generated_by"})


def _review_service() -> SubjectReviewService:
    return SubjectReviewService(default_subject_repo())


@router.get("", response_model=list[SubjectResponse])
async def list_subjects(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(active|paused)$"),
    _user: UserDomain = Depends(get_current_admin_user),
) -> list[SubjectResponse]:
    repo = default_subject_repo()
    subjects = await repo.list_subjects(status_filter)
    return [await _to_response(subject) for subject in subjects]


@router.post("", response_model=SubjectCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    request: SubjectCreateRequest,
    _user: UserDomain = Depends(get_current_admin_user),
) -> SubjectCreateResponse:
    repo = default_subject_repo()
    if await repo.active_count() >= MAX_ACTIVE_SUBJECTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已达议题上限，先停用旧议题",
        )
    subject = await repo.create_subject(
        name=request.name,
        nl_description=request.nl_description,
        keywords=request.keywords,
    )
    response = await _to_response(subject)
    return SubjectCreateResponse(**response.model_dump())


@router.get("/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: str,
    _user: UserDomain = Depends(get_current_admin_user),
) -> SubjectResponse:
    repo = default_subject_repo()
    subject = await repo.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    return await _to_response(subject)


@router.put("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: str,
    request: SubjectUpdateRequest,
    _user: UserDomain = Depends(get_current_admin_user),
) -> SubjectResponse:
    repo = default_subject_repo()
    subject = await repo.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    if (
        request.status == SubjectStatus.active.value
        and subject.status != SubjectStatus.active
        and await repo.active_count() >= MAX_ACTIVE_SUBJECTS
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已达议题上限，先停用旧议题",
        )
    updated = await repo.update_subject(
        subject_id,
        name=request.name,
        nl_description=request.nl_description,
        keywords=request.keywords,
        status=SubjectStatus(request.status) if request.status else None,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    return await _to_response(updated)


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: str,
    _user: UserDomain = Depends(get_current_admin_user),
) -> None:
    repo = default_subject_repo()
    subject = await repo.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    deleted = await repo.delete_subject(subject_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    return None


@router.get("/{subject_id}/feed")
async def get_subject_feed(  # type: ignore[no-untyped-def]  # 无 response_model，补返回标注会漂移，保持无标注
    subject_id: str,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
    time_axis: str | None = Query(default=None, pattern="^(ingest|publish)$"),
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = default_subject_repo()
    if await repo.get_subject(subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    until_dt = datetime.fromisoformat(until.replace("Z", "+00:00")) if until else None
    return await repo.get_subject_feed(
        subject_id,
        since=since_dt,
        until=until_dt,
        limit=limit,
        time_axis=time_axis or "ingest",
    )


@router.get("/{subject_id}/digests")
async def get_subject_digests(  # type: ignore[no-untyped-def]  # 无 response_model，补返回标注会漂移，保持无标注
    subject_id: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 24,
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = default_subject_repo()
    if await repo.get_subject(subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None
    if start_dt or end_dt:
        digest = await repo.get_digest(subject_id, start=start_dt, end=end_dt)
        return {"items": [_digest_public(digest)] if digest else [], "count": 1 if digest else 0}
    digests = await repo.list_digests(subject_id, limit=limit)
    return {
        "items": [_digest_public(digest) for digest in digests],
        "count": len(digests),
        "generated_at": datetime.now(UTC),
    }


@router.get("/{subject_id}/review", response_model=SubjectReviewResponse)
async def get_subject_review(
    subject_id: str,
    _user: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    payload = await _review_service().get_review_payload(subject_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    section_ids = [
        tweet_id
        for section in payload.get("sections", [])
        for tweet_id in section.get("cited_tweet_ids", [])
    ]
    cards, missing = await default_subject_repo().get_tweet_cards_by_ids(section_ids)
    payload = {**payload, "cited_tweets": cards, "missing_tweet_ids": missing}
    return payload


@router.post(
    "/{subject_id}/review/refresh",
    response_model=SubjectReviewRefreshResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_subject_review(
    subject_id: str,
    _user: UserDomain = Depends(get_current_admin_user),
) -> SubjectReviewRefreshResponse:
    repo = default_subject_repo()
    if await repo.get_subject(subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SUBJECT_NOT_FOUND)
    await repo.set_pending(subject_id, review=True)
    return SubjectReviewRefreshResponse(task_id=None, pending=True, message=REVIEW_PENDING_MESSAGE)


@router.post(
    "/review/refresh",
    response_model=SubjectReviewRefreshResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_all_subject_reviews(
    _user: UserDomain = Depends(get_current_admin_user),
) -> SubjectReviewRefreshResponse:
    return SubjectReviewRefreshResponse(task_id=None, message=REVIEW_MIGRATED_MESSAGE)
