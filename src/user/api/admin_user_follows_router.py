"""管理员代理操作用户关注列表 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.preference.api.schemas import CreateFollowRequest, FollowResponse
from src.preference.infrastructure.preference_repository import (
    DuplicateError,
    NotFoundError as FollowNotFoundError,
    PreferenceRepository,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
)
from src.preference.services.preference_service import PreferenceService
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.user.infrastructure.repository import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/users/{user_id}/follows",
    tags=["admin-user-follows"],
)


async def _verify_user_exists(
    user_id: int, session: AsyncSession
) -> None:
    """验证目标用户存在，不存在则抛出 404。"""
    user_repo = UserRepository(session)
    user = await user_repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )


def _build_service(session: AsyncSession) -> PreferenceService:
    return PreferenceService(
        PreferenceRepository(session),
        ScraperConfigRepository(session),
    )


@router.get("", response_model=list[FollowResponse])
async def get_user_follows(
    user_id: int,
    admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[FollowResponse]:
    """获取指定用户的关注列表（管理员）。"""
    await _verify_user_exists(user_id, session)
    service = _build_service(session)
    follows = await service.get_follows(user_id)
    return [
        FollowResponse(
            id=f.id,
            user_id=f.user_id,
            username=f.username,
            created_at=f.created_at,
        )
        for f in follows
    ]


@router.post(
    "",
    response_model=FollowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_user_follow(
    user_id: int,
    request: CreateFollowRequest,
    admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> FollowResponse:
    """为指定用户添加关注（管理员）。"""
    await _verify_user_exists(user_id, session)
    service = _build_service(session)
    try:
        result = await service.add_follow(
            user_id=user_id, username=request.username
        )
    except FollowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except DuplicateError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该用户已关注 '{request.username}'",
        )
    return FollowResponse(
        id=result.id,
        user_id=result.user_id,
        username=result.username,
        created_at=result.created_at,
    )


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_follow(
    user_id: int,
    username: str,
    admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """为指定用户移除关注（管理员）。"""
    await _verify_user_exists(user_id, session)
    service = _build_service(session)
    try:
        await service.remove_follow(user_id, username)
    except FollowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
