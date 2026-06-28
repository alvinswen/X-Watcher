"""Subject admin REST routes。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.data_layer.provider import get_subject_repo
from src.subjects.api.schemas import (
    SubjectCreateRequest,
    SubjectCreateResponse,
    SubjectResponse,
    SubjectReviewRefreshResponse,
    SubjectReviewResponse,
    SubjectUpdateRequest,
)
from src.subjects.models import Subject, SubjectStatus
from src.subjects.services.review_service import SubjectReviewService
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

router = APIRouter(prefix="/api/admin/subjects", tags=["subjects"])
REVIEW_MIGRATED_MESSAGE = "综述生成已迁移至外部技能，刷新功能将在后续版本改为挂待办"


async def _to_response(subject: Subject) -> SubjectResponse:
    repo = get_subject_repo()
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


def _digest_public(digest) -> dict:
    return digest.model_dump(mode="json", exclude={"generated_by"})


def _review_service():
    return SubjectReviewService(get_subject_repo())


@router.get("", response_model=list[SubjectResponse])
async def list_subjects(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(active|paused)$"),
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = get_subject_repo()
    subjects = await repo.list_subjects(status_filter)
    return [await _to_response(subject) for subject in subjects]


@router.post("", response_model=SubjectCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    request: SubjectCreateRequest,
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = get_subject_repo()
    if await repo.active_count() >= 20:
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
):
    repo = get_subject_repo()
    subject = await repo.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    return await _to_response(subject)


@router.put("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: str,
    request: SubjectUpdateRequest,
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = get_subject_repo()
    subject = await repo.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    if (
        request.status == SubjectStatus.active.value
        and subject.status != SubjectStatus.active
        and await repo.active_count() >= 20
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    return await _to_response(updated)


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: str,
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = get_subject_repo()
    subject = await repo.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    deleted = await repo.delete_subject(subject_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    return None


@router.get("/{subject_id}/feed")
async def get_subject_feed(
    subject_id: str,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = get_subject_repo()
    if await repo.get_subject(subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    until_dt = datetime.fromisoformat(until.replace("Z", "+00:00")) if until else None
    return await repo.get_subject_feed(
        subject_id,
        since=since_dt,
        until=until_dt,
        limit=limit,
    )


@router.get("/{subject_id}/digests")
async def get_subject_digests(
    subject_id: str,
    hour: str | None = None,
    limit: int = 24,
    _user: UserDomain = Depends(get_current_admin_user),
):
    repo = get_subject_repo()
    if await repo.get_subject(subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    if hour:
        digest = await repo.get_digest(subject_id, hour)
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
):
    payload = await _review_service().get_review_payload(subject_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    return payload


@router.post(
    "/{subject_id}/review/refresh",
    response_model=SubjectReviewRefreshResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_subject_review(
    subject_id: str,
    _user: UserDomain = Depends(get_current_admin_user),
):
    if await get_subject_repo().get_subject(subject_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="议题不存在")
    return SubjectReviewRefreshResponse(task_id=None, message=REVIEW_MIGRATED_MESSAGE)


@router.post(
    "/review/refresh",
    response_model=SubjectReviewRefreshResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_all_subject_reviews(
    _user: UserDomain = Depends(get_current_admin_user),
):
    return SubjectReviewRefreshResponse(task_id=None, message=REVIEW_MIGRATED_MESSAGE)
