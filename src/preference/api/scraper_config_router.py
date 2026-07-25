"""管理员抓取配置 API 路由。

提供平台级抓取账号管理的 RESTful API 端点。
所有端点需要管理员认证。
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from src.data_layer.provider import get_follows_repo
from src.preference.api.schemas import (
    CreateScraperFollowRequest,
    FetchAnalysisResponse,
    PeriodStats,
    ScraperFollowResponse,
    SyncProfilesResponse,
    TweetTimeRangeResponse,
    UpdateScraperFollowRequest,
    XUserProfileResponse,
)
from src.preference.infrastructure.follow_store import (
    DuplicateError,
    NotFoundError,
)
from src.preference.services.scraper_config_service import ScraperConfigService
from src.shared.schemas import ErrorResponse
from src.user.api.auth import get_current_admin_user, get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

# 管理员路由器（需要管理员权限）
router = APIRouter(
    prefix="/api/admin/scraping",
    tags=["admin"],
)

# 公共只读路由器（普通用户可访问）
public_router = APIRouter(
    prefix="/api/scraping",
    tags=["scraping"],
)


async def _get_scraper_config_service() -> ScraperConfigService:
    """获取 ScraperConfigService 实例。

    Args:
    Returns:
        ScraperConfigService: 服务实例
    """
    repository = get_follows_repo()
    return ScraperConfigService(repository)


async def _list_follow_responses(
    service: ScraperConfigService,
    *,
    include_inactive: bool,
) -> list[ScraperFollowResponse]:
    follows = await service.get_all_follows(include_inactive=include_inactive)
    return [ScraperFollowResponse.from_domain(follow) for follow in follows]


async def _list_profile_responses() -> list[XUserProfileResponse]:
    from src.data_layer.provider import get_profile_repo

    profiles = await get_profile_repo().get_all_profiles()
    return [XUserProfileResponse.from_domain(profile) for profile in profiles]


@router.post(
    "/follows",
    response_model=ScraperFollowResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
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
        return ScraperFollowResponse.from_domain(result)
    except DuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"抓取账号 '{request.username}' 已存在"
        ) from e
    except Exception as e:
        logger.error(f"添加抓取账号失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="添加抓取账号失败"
        ) from e


@router.get(
    "/follows",
    response_model=list[ScraperFollowResponse],
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_scraper_follows(
    include_inactive: bool = Query(False, description="是否包含非活跃账号"),
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
        return await _list_follow_responses(
            service,
            include_inactive=include_inactive,
        )
    except Exception as e:
        logger.error(f"获取抓取账号列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取抓取账号列表失败"
        ) from e


@router.get(
    "/follows/tweet-time-range",
    response_model=list[TweetTimeRangeResponse],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_follows_tweet_time_range(
    admin: UserDomain = Depends(get_current_admin_user),
) -> list[TweetTimeRangeResponse]:
    """获取所有活跃账号的推文时间范围。

    返回每个活跃抓取账号在系统中的最早推文时间、最近推文时间和推文总数。

    Args:
        session: 数据库会话
        admin: 管理员用户

    Returns:
        list[TweetTimeRangeResponse]: 各账号的推文时间范围
    """
    from src.preference.services.scraper_config_service import get_tweet_time_ranges

    try:
        # 1. 获取所有活跃账号
        service = await _get_scraper_config_service()
        follows = await service.get_all_follows(include_inactive=False)
        usernames = [f.username for f in follows]

        if not usernames:
            return []

        # 2. 共享实现:取活跃账号推文时间范围(REST/MCP 两处共用,CHG-032 目标 2)
        ranges = await get_tweet_time_ranges(usernames)

        # 3. 组装结果（包括无推文的账号）
        return [
            TweetTimeRangeResponse(
                username=u,
                earliest_tweet_at=ranges[u][0],
                latest_tweet_at=ranges[u][1],
                tweet_count=ranges[u][2],
            )
            for u in usernames
        ]
    except Exception as e:
        logger.error(f"获取推文时间范围失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取推文时间范围失败",
        ) from e


# ==================== 用户档案端点 ====================


@router.get(
    "/follows/profiles",
    response_model=list[XUserProfileResponse],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_user_profiles(
    admin: UserDomain = Depends(get_current_admin_user),
) -> list[XUserProfileResponse]:
    """获取所有已缓存的用户档案信息。

    返回从 TwitterAPI.io 获取并缓存的 X 平台用户档案列表。
    """
    try:
        return await _list_profile_responses()
    except Exception as e:
        logger.error(f"获取用户档案列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户档案列表失败",
        ) from e


@router.post(
    "/follows/sync-profiles",
    response_model=SyncProfilesResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def sync_user_profiles(
    admin: UserDomain = Depends(get_current_admin_user),
) -> SyncProfilesResponse:
    """手动触发用户档案同步。

    查询所有有 platform_user_id 的活跃关注账号，
    批量调用 TwitterAPI.io 获取最新档案信息并更新缓存。
    """
    from src.data_layer.provider import get_profile_repo
    from src.preference.domain.models import XUserProfile
    from src.scraper.client import TwitterClient

    try:
        # 获取所有有 platform_user_id 的活跃 follows
        config_repo = get_follows_repo()
        follows = await config_repo.get_all_follows(include_inactive=False)
        user_ids = [f.platform_user_id for f in follows if f.platform_user_id]

        if not user_ids:
            return SyncProfilesResponse(
                synced=0,
                message="没有可同步的账号（无 platform_user_id）",
            )

        # 调用 API 获取用户信息(async with 确保 fetch_user_info_by_ids 抛出异常时
        # 连接仍被释放,修复此前 close() 未受 try/finally 保护的连接泄漏,CHG-032 目标 3)
        async with TwitterClient() as client:
            result = await client.fetch_user_info_by_ids(user_ids)

        from returns.result import Failure

        if isinstance(result, Failure):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"TwitterAPI.io 调用失败: {result.failure().message}",
            )

        users_data = result.unwrap()
        if not users_data:
            return SyncProfilesResponse(synced=0, message="API 返回空结果")

        # 转换并持久化
        now = datetime.now(UTC).replace(tzinfo=None)
        profiles = []
        raw_data_map: dict[str, dict[str, Any]] = {}
        for u in users_data:
            profile = XUserProfile.from_api_response(u, fetched_at=now)
            if profile.platform_user_id:
                profiles.append(profile)
                raw_data_map[profile.platform_user_id] = u

        profile_repo = get_profile_repo()
        count = await profile_repo.upsert_profiles(profiles, raw_data_map=raw_data_map)

        return SyncProfilesResponse(
            synced=count,
            message=f"成功同步 {count} 个用户档案",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手动档案同步失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="档案同步失败",
        ) from e


@router.get(
    "/follows/{username}/profile",
    response_model=XUserProfileResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_user_profile(
    username: str,
    admin: UserDomain = Depends(get_current_admin_user),
) -> XUserProfileResponse:
    """获取指定用户的档案信息。"""
    from src.data_layer.provider import get_profile_repo

    try:
        repo = get_profile_repo()
        profile = await repo.get_profile_by_username(username)

        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"用户 {username} 的档案不存在（可能尚未同步）",
            )

        return XUserProfileResponse.from_domain(profile)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户档案失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户档案失败",
        ) from e


@router.put(
    "/follows/{username}",
    response_model=ScraperFollowResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
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
            manual_limit=request.manual_limit,
            brief_intro=request.brief_intro,
        )
        logger.info(f"管理员更新抓取账号: {username}")
        return ScraperFollowResponse.from_domain(result)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"抓取账号 '@{username}' 不存在"
        ) from e
    except Exception as e:
        logger.error(f"更新抓取账号失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新抓取账号失败"
        ) from e


@router.delete(
    "/follows/{username}",
    status_code=status.HTTP_204_NO_CONTENT,
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
            status_code=status.HTTP_404_NOT_FOUND, detail=f"抓取账号 '@{username}' 不存在"
        ) from e
    except Exception as e:
        logger.error(f"删除抓取账号失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除抓取账号失败"
        ) from e


# ==================== 抓取分析端点 ====================


@router.get(
    "/follows/{username}/analysis",
    response_model=FetchAnalysisResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_follow_analysis(
    username: str,
    interval_hours: int = Query(12, ge=12, le=24, description="周期间隔（12 或 24 小时）"),
    periods: int = Query(14, ge=1, le=30, description="查询周期数"),
    admin: UserDomain = Depends(get_current_admin_user),
) -> FetchAnalysisResponse:
    """获取指定账号的抓取结果分析。

    按指定的时间间隔统计过去 N 个周期内每个周期的新推文数量。

    Args:
        username: Twitter 用户名
        interval_hours: 周期间隔（12 或 24 小时）
        periods: 查询周期数（默认 14）
        session: 数据库会话
        admin: 管理员用户
    """
    from src.data_layer.provider import get_scraper_stats_repo

    try:
        # 显式窗口逐周期 count 走 provider 的文件仓储 Python 计数。
        # 结果已正序(最早在前),无 round 陷阱。
        windows = await get_scraper_stats_repo().period_analysis(username, interval_hours, periods)

        period_stats = [
            PeriodStats(
                period_start=period_start,
                period_end=period_end,
                new_tweet_count=count,
            )
            for (period_start, period_end, count) in windows
        ]
        total = sum(count for (_ps, _pe, count) in windows)

        return FetchAnalysisResponse(
            username=username,
            interval_hours=interval_hours,
            periods=period_stats,
            total_new_tweets=total,
        )
    except Exception as e:
        logger.error(f"获取抓取分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取抓取分析失败",
        ) from e


# ==================== 公共只读端点 ====================


@public_router.get(
    "/follows",
    response_model=list[ScraperFollowResponse],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
)
async def get_scraper_follows_public(
    service: ScraperConfigService = Depends(_get_scraper_config_service),
    current_user: UserDomain = Depends(get_current_user),
) -> list[ScraperFollowResponse]:
    """获取平台抓取账号列表（只读）。

    普通用户可访问此端点查看平台正在抓取的账号及其描述信息。
    仅返回活跃账号。

    Args:
        service: 抓取配置服务
        current_user: 当前认证用户（普通用户即可）

    Returns:
        list[ScraperFollowResponse]: 活跃抓取账号列表
    """
    try:
        return await _list_follow_responses(
            service,
            include_inactive=False,
        )
    except Exception as e:
        logger.error(f"获取抓取账号列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取抓取账号列表失败"
        ) from e


@public_router.get(
    "/follows/profiles",
    response_model=list[XUserProfileResponse],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
)
async def get_user_profiles_public(
    current_user: UserDomain = Depends(get_current_user),
) -> list[XUserProfileResponse]:
    """获取用户档案列表（只读）。

    普通用户可访问此端点查看已缓存的用户档案信息。
    """
    try:
        return await _list_profile_responses()
    except Exception as e:
        logger.error(f"获取用户档案列表失败（公共）: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户档案列表失败",
        ) from e
