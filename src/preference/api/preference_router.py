"""用户偏好 API 路由。

提供用户关注列表、过滤规则和排序偏好管理的 RESTful API 端点。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.preference.api.schemas import (
    CreateFollowRequest,
    FollowResponse,
    UpdatePriorityRequest,
    CreateFilterRequest,
    FilterResponse,
    UpdateSortingRequest,
    SortingPreferenceResponse,
    PreferenceResponse,
    DeleteResponse,
    ErrorResponse,
    TweetWithRelevance,
    SortType,
)
from src.preference.domain.models import TwitterFollow, FilterRule
from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    NotFoundError,
    DuplicateError,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
)
from src.preference.services.preference_service import PreferenceService
from src.preference.services.relevance_service import KeywordRelevanceService
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
    relevance_service = KeywordRelevanceService()
    return PreferenceService(
        preference_repository=preference_repo,
        scraper_config_repository=scraper_config_repo,
        relevance_service=relevance_service,
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
        priority=follow.priority,
        created_at=follow.created_at,
        updated_at=follow.updated_at,
    )


def _filter_domain_to_response(rule: FilterRule) -> FilterResponse:
    """将过滤规则领域模型转换为响应模型。

    Args:
        rule: FilterRule 领域模型

    Returns:
        FilterResponse: API 响应模型
    """
    return FilterResponse(
        id=rule.id,
        user_id=rule.user_id,
        filter_type=rule.filter_type,
        value=rule.value,
        created_at=rule.created_at,
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
            priority=request.priority,
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
    sort: SortType | None = Query(None, description="排序方式"),
    service: PreferenceService = Depends(_get_preference_service),
) -> list[FollowResponse]:
    """获取用户关注列表。

    返回用户的所有关注记录，可选按优先级排序。

    Args:
        current_user: 当前认证用户
        sort: 排序方式（priority 或 None）
        service: 偏好服务

    Returns:
        list[FollowResponse]: 关注记录列表
    """
    try:
        result = await service.get_follows(current_user.id, sort_by=sort)
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


@router.put(
    "/follows/{username}/priority",
    response_model=FollowResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def update_follow_priority(
    username: str,
    request: UpdatePriorityRequest,
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> FollowResponse:
    """更新关注账号的优先级。

    Args:
        username: Twitter 用户名
        request: 更新优先级请求
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        FollowResponse: 更新后的关注记录

    Raises:
        HTTPException: 如果关注记录不存在（404）
    """
    try:
        result = await service.update_priority(
            user_id=current_user.id,
            username=username,
            priority=request.priority,
        )
        return _domain_to_response(result)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"关注记录 '@{username}' 不存在"
        ) from e
    except Exception as e:
        logger.error(f"更新优先级失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新优先级失败"
        ) from e


@router.post(
    "/filters",
    response_model=FilterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def create_filter(
    request: CreateFilterRequest,
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> FilterResponse:
    """添加内容过滤规则。

    Args:
        request: 创建过滤规则请求
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        FilterResponse: 创建的过滤规则

    Raises:
        HTTPException: 如果规则已存在（409）
    """
    try:
        result = await service.add_filter(
            user_id=current_user.id,
            filter_type=request.filter_type,
            value=request.value,
        )
        return _filter_domain_to_response(result)
    except DuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"过滤规则已存在: {request.value}"
        ) from e
    except Exception as e:
        logger.error(f"添加过滤规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="添加过滤规则失败"
        ) from e


@router.get(
    "/filters",
    response_model=list[FilterResponse],
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_filters(
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> list[FilterResponse]:
    """获取用户的过滤规则列表。

    Args:
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        list[FilterResponse]: 过滤规则列表
    """
    try:
        result = await service.get_filters(current_user.id)
        return [_filter_domain_to_response(f) for f in result]
    except Exception as e:
        logger.error(f"获取过滤规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取过滤规则失败"
        ) from e


@router.delete(
    "/filters/{rule_id}",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def delete_filter(
    rule_id: str,
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> Response:
    """删除过滤规则。

    Args:
        rule_id: 过滤规则 ID（UUID）
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        Response: 204 No Content 响应

    Raises:
        HTTPException: 如果过滤规则不存在（404）
    """
    try:
        await service.remove_filter(current_user.id, rule_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"过滤规则 '{rule_id}' 不存在"
        )
    except Exception as e:
        logger.error(f"删除过滤规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除过滤规则失败"
        ) from e


@router.put(
    "/sorting",
    response_model=SortingPreferenceResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def update_sorting_preference(
    request: UpdateSortingRequest,
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> SortingPreferenceResponse:
    """更新新闻流排序偏好。

    Args:
        request: 更新排序偏好请求
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        SortingPreferenceResponse: 更新后的排序偏好
    """
    try:
        result = await service.update_sorting_preference(
            user_id=current_user.id,
            sort_type=request.sort_type,
        )
        return SortingPreferenceResponse(sort_type=result)
    except Exception as e:
        logger.error(f"更新排序偏好失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新排序偏好失败"
        ) from e


@router.get(
    "/sorting",
    response_model=SortingPreferenceResponse,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_sorting_preference(
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> SortingPreferenceResponse:
    """获取新闻流排序偏好。

    Args:
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        SortingPreferenceResponse: 当前排序偏好
    """
    try:
        result = await service.get_sorting_preference(current_user.id)
        return SortingPreferenceResponse(sort_type=result)
    except Exception as e:
        logger.error(f"获取排序偏好失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取排序偏好失败"
        ) from e


@router.get(
    "",
    response_model=PreferenceResponse,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_preferences(
    current_user: UserDomain = Depends(get_current_user),
    service: PreferenceService = Depends(_get_preference_service),
) -> PreferenceResponse:
    """获取用户的所有偏好配置。

    Args:
        current_user: 当前认证用户
        service: 偏好服务

    Returns:
        PreferenceResponse: 所有偏好配置
    """
    try:
        user_id = current_user.id

        # 获取排序偏好
        sort_type = await service.get_sorting_preference(user_id)

        # 获取关注列表
        follows = await service.get_follows(user_id)

        # 获取过滤规则
        filters = await service.get_filters(user_id)

        return PreferenceResponse(
            user_id=user_id,
            sorting=SortingPreferenceResponse(sort_type=sort_type),
            follows=[_domain_to_response(f) for f in follows],
            filters=[_filter_domain_to_response(f) for f in filters],
        )
    except Exception as e:
        logger.error(f"获取偏好配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取偏好配置失败"
        ) from e


@router.get(
    "/news",
    response_model=list[TweetWithRelevance],
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def get_sorted_news(
    current_user: UserDomain = Depends(get_current_user),
    sort: SortType = Query(SortType.TIME, description="排序方式"),
    limit: int = Query(100, ge=1, le=1000, description="最大返回数量"),
    service: PreferenceService = Depends(_get_preference_service),
) -> list[TweetWithRelevance]:
    """获取个性化新闻流。

    根据用户的关注列表、过滤规则和排序偏好返回排序后的推文。

    Args:
        current_user: 当前认证用户
        sort: 排序方式（time/relevance/priority）
        limit: 最大返回数量
        service: 偏好服务

    Returns:
        list[TweetWithRelevance]: 排序后的推文列表
    """
    try:
        result = await service.get_sorted_news(
            user_id=current_user.id,
            sort_type=sort,
            limit=limit,
        )
        return [
            TweetWithRelevance(
                tweet=item["tweet"],
                relevance_score=item.get("relevance_score"),
            )
            for item in result
        ]
    except Exception as e:
        logger.error(f"获取新闻流失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取新闻流失败"
        ) from e
