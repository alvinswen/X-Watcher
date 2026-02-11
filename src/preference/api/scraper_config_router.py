"""管理员抓取配置 API 路由。

提供平台级抓取账号管理的 RESTful API 端点。
所有端点需要管理员认证。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.preference.api.schemas import (
    CreateScraperFollowRequest,
    ScraperFollowResponse,
    UpdateScraperFollowRequest,
    DeleteResponse,
    ErrorResponse,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
    NotFoundError,
    DuplicateError,
    RepositoryError,
)
from src.preference.services.scraper_config_service import ScraperConfigService


logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/api/admin/scraping",
    tags=["admin"],
)


async def _get_scraper_config_service(
    session: AsyncSession = Depends(get_async_session),
) -> ScraperConfigService:
    """获取 ScraperConfigService 实例。

    Args:
        session: 数据库会话

    Returns:
        ScraperConfigService: 服务实例
    """
    repository = ScraperConfigRepository(session)
    return ScraperConfigService(repository)


@router.post(
    "/follows",
    response_model=ScraperFollowResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
async def add_scraper_follow(
    request: CreateScraperFollowRequest,
    service: ScraperConfigService = Depends(_get_scraper_config_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScraperFollowResponse:
    """添加平台抓取账号。

    管理员通过此端点添加新的 Twitter 账号到平台抓取列表。
    用户关注列表初始化时会复制这些账号。

    Args:
        request: 创建抓取账号请求
        service: 抓取配置服务
        admin: 管理员用户

    Returns:
        ScraperFollowResponse: 创建的抓取账号信息

    Raises:
        HTTPException: 如果账号已存在（409）或验证失败（422）
    """
    try:
        result = await service.add_scraper_follow(
            username=request.username,
            reason=request.reason,
            added_by=request.added_by,
        )
        logger.info(f"管理员添加抓取账号: {request.username} by {request.added_by}")
        return ScraperFollowResponse(
            id=result.id,
            username=result.username,
            added_at=result.added_at,
            reason=result.reason,
            added_by=result.added_by,
            is_active=result.is_active,
        )
    except DuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"抓取账号 '{request.username}' 已存在"
        ) from e
    except Exception as e:
        logger.error(f"添加抓取账号失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="添加抓取账号失败"
        ) from e


@router.get(
    "/follows",
    response_model=list[ScraperFollowResponse],
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_scraper_follows(
    include_inactive: bool = Query(
        False,
        description="是否包含非活跃账号"
    ),
    service: ScraperConfigService = Depends(_get_scraper_config_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> list[ScraperFollowResponse]:
    """获取平台抓取账号列表。

    返回所有（或仅活跃的）平台抓取账号。

    Args:
        include_inactive: 是否包含非活跃账号
        service: 抓取配置服务
        admin: 管理员用户

    Returns:
        list[ScraperFollowResponse]: 抓取账号列表
    """
    try:
        result = await service.get_all_follows(
            include_inactive=include_inactive
        )
        return [
            ScraperFollowResponse(
                id=f.id,
                username=f.username,
                added_at=f.added_at,
                reason=f.reason,
                added_by=f.added_by,
                is_active=f.is_active,
            )
            for f in result
        ]
    except Exception as e:
        logger.error(f"获取抓取账号列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取抓取账号列表失败"
        ) from e


@router.put(
    "/follows/{username}",
    response_model=ScraperFollowResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
async def update_scraper_follow(
    username: str,
    request: UpdateScraperFollowRequest,
    service: ScraperConfigService = Depends(_get_scraper_config_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScraperFollowResponse:
    """更新平台抓取账号。

    更新指定账号的添加理由或活跃状态。

    Args:
        username: Twitter 用户名
        request: 更新请求
        service: 抓取配置服务
        admin: 管理员用户

    Returns:
        ScraperFollowResponse: 更新后的抓取账号信息

    Raises:
        HTTPException: 如果账号不存在（404）
    """
    try:
        result = await service.update_follow(
            username=username,
            reason=request.reason,
            is_active=request.is_active,
        )
        logger.info(f"管理员更新抓取账号: {username}")
        return ScraperFollowResponse(
            id=result.id,
            username=result.username,
            added_at=result.added_at,
            reason=result.reason,
            added_by=result.added_by,
            is_active=result.is_active,
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"抓取账号 '@{username}' 不存在"
        ) from e
    except Exception as e:
        logger.error(f"更新抓取账号失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新抓取账号失败"
        ) from e


@router.delete(
    "/follows/{username}",
    response_model=DeleteResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_scraper_follow(
    username: str,
    service: ScraperConfigService = Depends(_get_scraper_config_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> Response:
    """删除（软删除）平台抓取账号。

    将指定账号标记为非活跃状态，而不是从数据库中删除。

    Args:
        username: Twitter 用户名
        service: 抓取配置服务
        admin: 管理员用户

    Returns:
        Response: 204 No Content 响应

    Raises:
        HTTPException: 如果账号不存在（404）
    """
    try:
        await service.deactivate_follow(username)
        logger.info(f"管理员删除抓取账号: {username}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"抓取账号 '@{username}' 不存在"
        ) from e
    except Exception as e:
        logger.error(f"删除抓取账号失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除抓取账号失败"
        ) from e
