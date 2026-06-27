"""系统状态概览 API 路由。

提供 GET /api/status/overview 端点，聚合返回推文、关注、摘要和系统维度的关键指标。
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.models import ScraperFollow
from src.scraper.infrastructure.models import TweetOrm
from src.shared.schemas import UTCDatetimeModel
from src.summarization.infrastructure.models import SummaryOrm
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/status", tags=["status"])


# ── 响应模型 ──────────────────────────────────────────────


# TweetStats/FollowStats/SummaryStats 抽到 src/api/status_schemas.py(断 status→main 循环,
# 供文件层 status 门面共享);此处 re-import 保持本模块引用不变。
from src.api.status_schemas import (  # noqa: E402
    FollowStats,
    SummaryStats,
    TweetStats,
)


class SystemStats(UTCDatetimeModel):
    server_start_time: datetime | None
    database_size_mb: float | None


class StatusOverviewResponse(BaseModel):
    tweets: TweetStats
    follows: FollowStats
    summaries: SummaryStats
    system: SystemStats


class TwitterBalanceResponse(UTCDatetimeModel):
    recharge_credits: int | None
    fetched_at: datetime | None
    source: str  # "live" | "cache" | "stale" | "error"
    error: str | None = None
    warning_threshold: int
    danger_threshold: int


# ── 端点 ──────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=StatusOverviewResponse,
    summary="系统状态概览",
    description="聚合返回推文、关注、摘要和系统维度的关键指标。",
)
async def get_status_overview(
    current_user: UserDomain = Depends(get_current_user),
) -> StatusOverviewResponse:
    """获取系统状态概览。"""
    from src.data_layer.provider import get_status_repo
    from src.database.async_session import get_async_session_maker

    session_maker = get_async_session_maker()

    async def _tweets():
        async with session_maker() as s:
            return await get_status_repo(s).get_tweet_stats()

    async def _follows():
        async with session_maker() as s:
            return await get_status_repo(s).get_follow_stats()

    async def _summaries():
        async with session_maker() as s:
            return await get_status_repo(s).get_summary_stats()

    tweets, follows, summaries = await asyncio.gather(
        _tweets(),
        _follows(),
        _summaries(),
    )
    system = _get_system_stats()

    return StatusOverviewResponse(
        tweets=tweets,
        follows=follows,
        summaries=summaries,
        system=system,
    )


@router.get(
    "/twitter-balance",
    response_model=TwitterBalanceResponse,
    summary="TwitterAPI.io 账户余额",
    description=(
        "查询 TwitterAPI.io 账户剩余 credits。结果默认缓存 10 分钟，"
        "可通过 ?force=true 强制刷新。响应同时返回前端用于变色判断的告警阈值。"
    ),
)
async def get_twitter_balance(
    force: bool = False,
    current_user: UserDomain = Depends(get_current_user),
) -> TwitterBalanceResponse:
    """获取 TwitterAPI.io 账户余额。"""
    from src.scraper.account_info_service import get_account_info_service

    service = get_account_info_service()
    settings = get_settings()
    data = await service.get_balance(force_refresh=force)

    return TwitterBalanceResponse(
        recharge_credits=data["recharge_credits"],
        fetched_at=data["fetched_at"],
        source=data["source"],
        error=data["error"],
        warning_threshold=settings.twitter_balance_warning_threshold,
        danger_threshold=settings.twitter_balance_danger_threshold,
    )


# ── 查询辅助函数 ──────────────────────────────────────────


async def _get_tweet_stats(session: AsyncSession) -> TweetStats:
    """推文统计。"""
    total_result = await session.execute(select(func.count()).select_from(TweetOrm))
    total = total_result.scalar() or 0

    latest_result = await session.execute(select(func.max(TweetOrm.created_at)))
    latest_tweet_at = latest_result.scalar()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await session.execute(
        select(func.count()).select_from(TweetOrm).where(TweetOrm.created_at >= today_start)
    )
    today_count = today_result.scalar() or 0

    return TweetStats(
        total=total,
        latest_tweet_at=latest_tweet_at,
        today_count=today_count,
    )


async def _get_follow_stats(session: AsyncSession) -> FollowStats:
    """关注账号统计。"""
    total_result = await session.execute(select(func.count()).select_from(ScraperFollow))
    total = total_result.scalar() or 0

    active_result = await session.execute(
        select(func.count())
        .select_from(ScraperFollow)
        .where(ScraperFollow.is_active == True)  # noqa: E712
    )
    active = active_result.scalar() or 0

    return FollowStats(total=total, active=active, inactive=total - active)


async def _get_summary_stats(session: AsyncSession) -> SummaryStats:
    """摘要统计。"""
    total_result = await session.execute(select(func.count()).select_from(SummaryOrm))
    total = total_result.scalar() or 0

    # 使用 LEFT JOIN + IS NULL 查找待摘要推文
    pending_result = await session.execute(
        select(func.count())
        .select_from(TweetOrm)
        .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
        .where(SummaryOrm.summary_id == None)  # noqa: E711
    )
    pending_tweets = pending_result.scalar() or 0

    return SummaryStats(total=total, pending_tweets=pending_tweets)


def get_server_start_time():
    """惰性委派 src.main，避免 status↔main 模块级循环（python -m src.main 双载触发）；
    保留为本模块级属性，以兼容测试对 src.api.routes.status.get_server_start_time 的 patch。"""
    from src.main import get_server_start_time as _impl

    return _impl()


def _get_system_stats() -> SystemStats:
    """系统统计。"""
    from src.database.dialect import get_database_size_mb

    server_start_time = get_server_start_time()
    database_size_mb = get_database_size_mb()

    return SystemStats(
        server_start_time=server_start_time,
        database_size_mb=database_size_mb,
    )
