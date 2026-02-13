"""用户关注列表 API 路由。

提供用户关注列表管理的 RESTful API 端点。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.preference.api.schemas import (
    CreateFollowRequest,
    FollowResponse,
    ErrorResponse,
)
from src.preference.domain.models import TwitterFollow
from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    NotFoundError,
    DuplicateError,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
)
from src.preference.services.preference_service import PreferenceService
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain


logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/api/preferences",
    tags=["preferences"],
)


async def _get_preference_service(
    session: AsyncSession = Depends(get_async_session),
) -> PreferenceService:
    """获取 PreferenceService 实例。

    Args:
        session: 数据库会话

    Returns:
        PreferenceService: 服务实例
    """
    preference_repo = PreferenceRepository(session)
    scraper_config_repo = ScraperConfigRepository(session)
    return PreferenceService(
        preference_repository=preference_repo,
        scraper_config_repository=scraper_config_repo,
    )


def _domain_to_response(follow: TwitterFollow) -> FollowResponse:
    """将领域模型转换为响应模型。

    Args:
        follow: Twitter 关注领域模型

    Returns:
        FollowResponse: API 响应模型
    """
    return FollowResponse(
        id=follow.id,
        user_id=follow.user_id,
        username=follow.username,
        created_at=follow.created_at,
    )


@router.post(
    "/follows",
    response_model=FollowResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
async def create_follow(
    request: CreateFollowRequest,
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> FollowResponse:
    """添加/恢复关注的 Twitter 账号。

    验证账号是否在平台抓取列表中，如果是则添加到用户关注列表。

    Args:
        request: 创建关注请求
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        FollowResponse: 创建的关注记录

    Raises:
        HTTPException: 如果账号不在抓取列表中（400）或已存在（409）
    """
    try:
        result = await service.add_follow(
            user_id=current_user.id,
            username=request.username,
        )
        return _domain_to_response(result)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e
    except DuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"关注记录 '{request.username}' 已存在"
        ) from e
    except Exception as e:
        logger.error(f"添加关注失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="添加关注失败"
        ) from e


@router.get(
    "/follows",
    response_model=list[FollowResponse],
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_follows(
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> list[FollowResponse]:
    """获取用户关注列表。

    返回用户的所有关注记录，按创建时间倒序。

    Args:
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        list[FollowResponse]: 关注记录列表
    """
    try:
        result = await service.get_follows(current_user.id)
        return [_domain_to_response(f) for f in result]
    except Exception as e:
        logger.error(f"获取关注列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取关注列表失败"
        ) from e


@router.delete(
    "/follows/{username}",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def delete_follow(
    username: str,
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> Response:
    """移除关注的 Twitter 账号。

    Args:
        username: Twitter 用户名
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        Response: 204 No Content 响应

    Raises:
        HTTPException: 如果关注记录不存在（404）
    """
    try:
        await service.remove_follow(current_user.id, username)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"关注记录 '@{username}' 不存在"
        ) from e
    except Exception as e:
        logger.error(f"移除关注失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="移除关注失败"
        ) from e
