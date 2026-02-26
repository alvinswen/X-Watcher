"""管理员抓取配置 API 路由。

提供平台级抓取账号管理的 RESTful API 端点。
所有端点需要管理员认证。
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.user.api.auth import get_current_admin_user, get_current_user
from src.user.domain.models import UserDomain
from src.preference.api.schemas import (
    CreateScraperFollowRequest,
    ScraperFollowResponse,
    UpdateScraperFollowRequest,
    DeleteResponse,
    ErrorResponse,
    ScheduleConfigResponse,
    UpdateScheduleIntervalRequest,
    UpdateScheduleNextRunRequest,
    FetchAnalysisResponse,
    FollowStatsResponse,
    PeriodStats,
    TweetTimeRangeResponse,
    XUserProfileResponse,
    SyncProfilesResponse,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
    NotFoundError,
    DuplicateError,
    RepositoryError,
)
from src.preference.services.scraper_config_service import ScraperConfigService
from src.topic.services.topic_summary_service import build_llm_providers


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
        return ScraperFollowResponse(
            id=result.id,
            username=result.username,
            platform_user_id=result.platform_user_id,
            added_at=result.added_at,
            reason=result.reason,
            added_by=result.added_by,
            is_active=result.is_active,
            manual_limit=result.manual_limit,
            brief_intro=result.brief_intro,
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
                platform_user_id=f.platform_user_id,
                added_at=f.added_at,
                reason=f.reason,
                added_by=f.added_by,
                is_active=f.is_active,
                manual_limit=f.manual_limit,
                brief_intro=f.brief_intro,
            )
            for f in result
        ]
    except Exception as e:
        logger.error(f"获取抓取账号列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取抓取账号列表失败"
        ) from e


@router.get(
    "/follows/stats",
    response_model=list[FollowStatsResponse],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_follows_stats(
    session: AsyncSession = Depends(get_async_session),
    admin: UserDomain = Depends(get_current_admin_user),
) -> list[FollowStatsResponse]:
    """获取所有活跃账号的运行时统计。

    返回每个账号的 effective_limit（自动模式下的计算值）和
    12h/24h 近期最大新推文数。

    Args:
        session: 数据库会话
        admin: 管理员用户

    Returns:
        list[FollowStatsResponse]: 各账号的运行时统计
    """
    from src.scraper.infrastructure.fetch_stats_repository import FetchStatsRepository
    from src.scraper.infrastructure.models import TweetOrm
    from src.scraper.services.limit_calculator import LimitCalculator

    try:
        # 1. 获取所有活跃账号
        service = await _get_scraper_config_service(session)
        follows = await service.get_all_follows(include_inactive=False)
        usernames = [f.username for f in follows]

        if not usernames:
            return []

        # 2. 批量查 FetchStats → 计算 effective_limit
        stats_repo = FetchStatsRepository(session)
        stats_map = await stats_repo.batch_get_stats(usernames)
        calculator = LimitCalculator()

        # 3. 高效批量查询：用单条 SQL 按 (username, period_bucket) 分组
        #    再在 Python 中按 username 聚合 max
        now = datetime.now(timezone.utc)
        num_periods = 14

        async def _batch_max_counts(
            interval_hours: int,
        ) -> dict[str, int]:
            """单条 SQL 查所有用户在指定间隔下的最大周期推文数。"""
            interval = timedelta(hours=interval_hours)
            cutoff = now - (num_periods * interval)

            # 一次查出所有用户在 cutoff 之后的推文，按 (username, period_bucket) 分组
            # period_bucket = floor((now - created_at) / interval)
            # SQLite 不支持 FLOOR 对 interval，用秒数计算
            interval_secs = int(interval.total_seconds())

            from sqlalchemy import cast, Integer

            from src.database.dialect import sql_epoch

            now_epoch = int(now.timestamp())
            bucket_expr = cast(
                (now_epoch - sql_epoch(TweetOrm.created_at, bind=session)) / interval_secs,
                Integer,
            )

            stmt = (
                select(
                    func.lower(TweetOrm.author_username).label("username_lower"),
                    func.count().label("cnt"),
                )
                .where(
                    func.lower(TweetOrm.author_username).in_([u.lower() for u in usernames]),
                    TweetOrm.created_at >= cutoff,
                    TweetOrm.created_at < now,
                )
                .group_by(func.lower(TweetOrm.author_username), bucket_expr)
            )

            result = await session.execute(stmt)
            rows = result.all()

            # 按 username 聚合 max(cnt)
            max_map: dict[str, int] = {}
            for username_val, cnt in rows:
                if username_val not in max_map or cnt > max_map[username_val]:
                    max_map[username_val] = cnt
            return max_map

        # 并行查 12h 和 24h（实际是顺序 await，但只有 2 条 SQL）
        max_12h_map = await _batch_max_counts(12)
        max_24h_map = await _batch_max_counts(24)

        # 4. 组装结果
        results = []
        for username in usernames:
            fetch_stats = stats_map.get(username)
            effective_limit = calculator.calculate_next_limit(fetch_stats)

            results.append(FollowStatsResponse(
                username=username,
                effective_limit=effective_limit,
                max_count_12h=max_12h_map.get(username.lower(), 0),
                max_count_24h=max_24h_map.get(username.lower(), 0),
            ))

        return results
    except Exception as e:
        logger.error(f"获取账号运行时统计失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取账号运行时统计失败",
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
    session: AsyncSession = Depends(get_async_session),
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
    from src.scraper.infrastructure.models import TweetOrm

    try:
        # 1. 获取所有活跃账号
        service = await _get_scraper_config_service(session)
        follows = await service.get_all_follows(include_inactive=False)
        usernames = [f.username for f in follows]

        if not usernames:
            return []

        # 2. 单条 SQL：按 author_username 分组查 min/max/count
        #    使用 lower() 进行大小写不敏感匹配，因为 Twitter API 返回的
        #    用户名大小写可能与 scraper_follows 中配置的不一致
        lower_usernames = [u.lower() for u in usernames]
        stmt = (
            select(
                func.lower(TweetOrm.author_username).label("username_lower"),
                func.min(TweetOrm.created_at).label("earliest"),
                func.max(TweetOrm.created_at).label("latest"),
                func.count().label("cnt"),
            )
            .where(func.lower(TweetOrm.author_username).in_(lower_usernames))
            .group_by(func.lower(TweetOrm.author_username))
        )
        result = await session.execute(stmt)
        rows = {r[0]: (r[1], r[2], r[3]) for r in result.all()}

        # 3. 组装结果（包括无推文的账号），通过 lower() 键匹配
        return [
            TweetTimeRangeResponse(
                username=u,
                earliest_tweet_at=rows[u.lower()][0] if u.lower() in rows else None,
                latest_tweet_at=rows[u.lower()][1] if u.lower() in rows else None,
                tweet_count=rows[u.lower()][2] if u.lower() in rows else 0,
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
    session: AsyncSession = Depends(get_async_session),
    admin: UserDomain = Depends(get_current_admin_user),
) -> list[XUserProfileResponse]:
    """获取所有已缓存的用户档案信息。

    返回从 TwitterAPI.io 获取并缓存的 X 平台用户档案列表。
    """
    from src.preference.infrastructure.x_user_profile_repository import (
        XUserProfileRepository,
    )

    try:
        repo = XUserProfileRepository(session)
        profiles = await repo.get_all_profiles()
        return [
            XUserProfileResponse(
                platform_user_id=p.platform_user_id,
                username=p.username,
                display_name=p.display_name,
                is_blue_verified=p.is_blue_verified,
                verified_type=p.verified_type,
                profile_picture=p.profile_picture,
                cover_picture=p.cover_picture,
                description=p.description,
                location=p.location,
                followers_count=p.followers_count,
                following_count=p.following_count,
                statuses_count=p.statuses_count,
                favourites_count=p.favourites_count,
                media_count=p.media_count,
                account_created_at=p.account_created_at,
                is_automated=p.is_automated,
                possibly_sensitive=p.possibly_sensitive,
                pinned_tweet_ids=p.pinned_tweet_ids,
                unavailable=p.unavailable,
                unavailable_reason=p.unavailable_reason,
                fetched_at=p.fetched_at,
            )
            for p in profiles
        ]
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
    session: AsyncSession = Depends(get_async_session),
    admin: UserDomain = Depends(get_current_admin_user),
) -> SyncProfilesResponse:
    """手动触发用户档案同步。

    查询所有有 platform_user_id 的活跃关注账号，
    批量调用 TwitterAPI.io 获取最新档案信息并更新缓存。
    """
    from src.preference.infrastructure.x_user_profile_repository import (
        XUserProfileRepository,
    )
    from src.preference.domain.models import XUserProfile
    from src.scraper.client import TwitterClient

    try:
        # 获取所有有 platform_user_id 的活跃 follows
        config_repo = ScraperConfigRepository(session)
        follows = await config_repo.get_all_follows(include_inactive=False)
        user_ids = [
            f.platform_user_id
            for f in follows
            if f.platform_user_id
        ]

        if not user_ids:
            return SyncProfilesResponse(
                synced=0,
                message="没有可同步的账号（无 platform_user_id）",
            )

        # 调用 API 获取用户信息
        client = TwitterClient()
        result = await client.fetch_user_info_by_ids(user_ids)
        await client.close()

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
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        profiles = []
        raw_data_map: dict[str, dict] = {}
        for u in users_data:
            profile = XUserProfile.from_api_response(u, fetched_at=now)
            if profile.platform_user_id:
                profiles.append(profile)
                raw_data_map[profile.platform_user_id] = u

        profile_repo = XUserProfileRepository(session)
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
    session: AsyncSession = Depends(get_async_session),
    admin: UserDomain = Depends(get_current_admin_user),
) -> XUserProfileResponse:
    """获取指定用户的档案信息。"""
    from src.preference.infrastructure.x_user_profile_repository import (
        XUserProfileRepository,
    )

    try:
        repo = XUserProfileRepository(session)
        profile = await repo.get_profile_by_username(username)

        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"用户 {username} 的档案不存在（可能尚未同步）",
            )

        return XUserProfileResponse(
            platform_user_id=profile.platform_user_id,
            username=profile.username,
            display_name=profile.display_name,
            is_blue_verified=profile.is_blue_verified,
            verified_type=profile.verified_type,
            profile_picture=profile.profile_picture,
            cover_picture=profile.cover_picture,
            description=profile.description,
            location=profile.location,
            followers_count=profile.followers_count,
            following_count=profile.following_count,
            statuses_count=profile.statuses_count,
            favourites_count=profile.favourites_count,
            media_count=profile.media_count,
            account_created_at=profile.account_created_at,
            is_automated=profile.is_automated,
            possibly_sensitive=profile.possibly_sensitive,
            pinned_tweet_ids=profile.pinned_tweet_ids,
            unavailable=profile.unavailable,
            unavailable_reason=profile.unavailable_reason,
            fetched_at=profile.fetched_at,
        )
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
        return ScraperFollowResponse(
            id=result.id,
            username=result.username,
            platform_user_id=result.platform_user_id,
            added_at=result.added_at,
            reason=result.reason,
            added_by=result.added_by,
            is_active=result.is_active,
            manual_limit=result.manual_limit,
            brief_intro=result.brief_intro,
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


@router.post(
    "/follows/{username}/generate-intro",
    response_model=ScraperFollowResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def generate_follow_intro(
    username: str,
    session: AsyncSession = Depends(get_async_session),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScraperFollowResponse:
    """为指定关注账号生成极简介绍。

    查询用户档案，调用 LLM 生成 ≤10 汉字的极简介绍并保存。
    """
    from src.preference.infrastructure.x_user_profile_repository import (
        XUserProfileRepository,
    )

    try:
        # 查询 follow
        config_repo = ScraperConfigRepository(session)
        follow = await config_repo.get_follow_by_username(username)
        if follow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"抓取账号 '@{username}' 不存在",
            )

        # 查询档案
        profile_repo = XUserProfileRepository(session)
        profile = await profile_repo.get_profile_by_username(username)
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"用户 {username} 的档案不存在（请先同步档案）",
            )

        display_name = profile.display_name or username
        description = profile.description or ""

        # 调用 LLM
        providers = build_llm_providers()
        if not providers:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="没有可用的 LLM 提供商",
            )

        prompt = (
            "根据以下 Twitter 账号信息，生成一个不超过10个汉字的中文极简介绍。\n"
            f"显示名: {display_name}\n"
            f"个人简介: {description}\n"
            "只输出介绍文本，不要包含引号、标点或额外说明。"
        )

        from returns.result import Success as SuccessResult

        llm_result = None
        for provider in providers:
            try:
                result = await provider.complete(
                    prompt=prompt, max_tokens=100, temperature=0.3,
                )
                if isinstance(result, SuccessResult):
                    llm_result = result.unwrap()
                    break
            except Exception as e:
                logger.warning(f"Provider {provider.get_provider_name()} 调用失败: {e}")

        if llm_result is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="所有 LLM 提供商均失败",
            )

        brief_intro = llm_result.content.strip()[:50]

        # 保存
        updated = await config_repo.update_scraper_follow(
            username=username, brief_intro=brief_intro,
        )
        await session.commit()

        return ScraperFollowResponse(
            id=updated.id,
            username=updated.username,
            platform_user_id=updated.platform_user_id,
            added_at=updated.added_at,
            reason=updated.reason,
            added_by=updated.added_by,
            is_active=updated.is_active,
            manual_limit=updated.manual_limit,
            brief_intro=updated.brief_intro,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成极简介绍失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成极简介绍失败",
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


# ==================== 调度配置管理端点 ====================


async def _get_schedule_service():
    """获取 ScraperScheduleService 实例。

    ScraperScheduleService 内部自行管理 session 生命周期，
    每次 DB 操作使用独立的短生命周期 session，避免 PendingRollbackError。
    """
    from src.preference.services.schedule_service import ScraperScheduleService

    return ScraperScheduleService()


@router.get(
    "/schedule",
    response_model=ScheduleConfigResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def get_schedule_config(
    service=Depends(_get_schedule_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScheduleConfigResponse:
    """查看当前调度配置。"""
    try:
        return await service.get_schedule_config()
    except Exception as e:
        logger.error(f"获取调度配置失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取调度配置失败",
        ) from e


@router.put(
    "/schedule/interval",
    response_model=ScheduleConfigResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def update_schedule_interval(
    request: UpdateScheduleIntervalRequest,
    service=Depends(_get_schedule_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScheduleConfigResponse:
    """更新抓取间隔。"""
    try:
        return await service.update_interval(
            interval_seconds=request.interval_seconds,
            updated_by=admin.name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新调度间隔失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="调度器操作失败",
        ) from e


@router.put(
    "/schedule/next-run",
    response_model=ScheduleConfigResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def update_schedule_next_run(
    request: UpdateScheduleNextRunRequest,
    service=Depends(_get_schedule_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScheduleConfigResponse:
    """设置下次触发时间。"""
    try:
        return await service.update_next_run_time(
            next_run_time=request.next_run_time,
            updated_by=admin.name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置下次触发时间失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="调度器操作失败",
        ) from e


@router.post(
    "/schedule/enable",
    response_model=ScheduleConfigResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def enable_schedule(
    service=Depends(_get_schedule_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScheduleConfigResponse:
    """启用调度。

    从 DB 恢复配置并创建 scraper_job。
    如果无配置，返回 422 提示先设置间隔。
    """
    try:
        return await service.enable_schedule(updated_by=admin.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启用调度失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="启用调度失败",
        ) from e


@router.post(
    "/schedule/disable",
    response_model=ScheduleConfigResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    },
)
async def disable_schedule(
    service=Depends(_get_schedule_service),
    admin: UserDomain = Depends(get_current_admin_user),
) -> ScheduleConfigResponse:
    """暂停调度。

    移除 scraper_job 但保留 DB 中的调度配置。
    """
    try:
        return await service.disable_schedule(updated_by=admin.name)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停调度失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="暂停调度失败",
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
    session: AsyncSession = Depends(get_async_session),
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
    from src.scraper.infrastructure.models import TweetOrm

    try:
        now = datetime.now(timezone.utc)
        interval = timedelta(hours=interval_hours)

        period_stats = []
        total = 0

        for i in range(periods):
            period_end = now - (i * interval)
            period_start = period_end - interval

            stmt = (
                select(func.count())
                .select_from(TweetOrm)
                .where(
                    func.lower(TweetOrm.author_username) == username.lower(),
                    TweetOrm.created_at >= period_start,
                    TweetOrm.created_at < period_end,
                )
            )
            result = await session.execute(stmt)
            count = result.scalar() or 0

            period_stats.append(PeriodStats(
                period_start=period_start,
                period_end=period_end,
                new_tweet_count=count,
            ))
            total += count

        # 按时间正序排列（最早的在前）
        period_stats.reverse()

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
        result = await service.get_all_follows(include_inactive=False)
        return [
            ScraperFollowResponse(
                id=f.id,
                username=f.username,
                platform_user_id=f.platform_user_id,
                added_at=f.added_at,
                reason=f.reason,
                added_by=f.added_by,
                is_active=f.is_active,
                manual_limit=f.manual_limit,
                brief_intro=f.brief_intro,
            )
            for f in result
        ]
    except Exception as e:
        logger.error(f"获取抓取账号列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取抓取账号列表失败"
        ) from e


@public_router.get(
    "/follows/profiles",
    response_model=list[XUserProfileResponse],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
)
async def get_user_profiles_public(
    session: AsyncSession = Depends(get_async_session),
    current_user: UserDomain = Depends(get_current_user),
) -> list[XUserProfileResponse]:
    """获取用户档案列表（只读）。

    普通用户可访问此端点查看已缓存的用户档案信息。
    """
    from src.preference.infrastructure.x_user_profile_repository import (
        XUserProfileRepository,
    )

    try:
        repo = XUserProfileRepository(session)
        profiles = await repo.get_all_profiles()
        return [
            XUserProfileResponse(
                platform_user_id=p.platform_user_id,
                username=p.username,
                display_name=p.display_name,
                is_blue_verified=p.is_blue_verified,
                verified_type=p.verified_type,
                profile_picture=p.profile_picture,
                cover_picture=p.cover_picture,
                description=p.description,
                location=p.location,
                followers_count=p.followers_count,
                following_count=p.following_count,
                statuses_count=p.statuses_count,
                favourites_count=p.favourites_count,
                media_count=p.media_count,
                account_created_at=p.account_created_at,
                is_automated=p.is_automated,
                possibly_sensitive=p.possibly_sensitive,
                pinned_tweet_ids=p.pinned_tweet_ids,
                unavailable=p.unavailable,
                unavailable_reason=p.unavailable_reason,
                fetched_at=p.fetched_at,
            )
            for p in profiles
        ]
    except Exception as e:
        logger.error(f"获取用户档案列表失败（公共）: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户档案列表失败",
        ) from e
