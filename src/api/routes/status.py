"""系统状态概览 API 路由。

提供 GET /api/status/overview 端点，聚合返回推文、关注、摘要、主题、调度器和系统维度的关键指标。
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.async_session import get_db_session
from src.database.models import ScraperFollow
from src.main import get_server_start_time
from src.scheduler_accessor import get_scheduler
from src.scraper.infrastructure.models import TweetOrm
from src.shared.schemas import UTCDatetimeModel
from src.summarization.infrastructure.models import SummaryOrm
from src.topic.infrastructure.models import TopicOrm, TopicSummaryTaskOrm
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/status", tags=["status"])


# ── 响应模型 ──────────────────────────────────────────────


class TweetStats(BaseModel):
    total: int
    latest_tweet_at: datetime | None
    today_count: int


class FollowStats(BaseModel):
    total: int
    active: int
    inactive: int


class SummaryStats(BaseModel):
    total: int
    pending_tweets: int


class TopicStats(BaseModel):
    total: int
    latest_summary_at: datetime | None
    latest_summary_status: str | None


class SchedulerStats(BaseModel):
    status: str
    next_run_time: datetime | None
    interval_seconds: int


class SystemStats(UTCDatetimeModel):
    server_start_time: datetime | None
    database_size_mb: float | None


class StatusOverviewResponse(BaseModel):
    tweets: TweetStats
    follows: FollowStats
    summaries: SummaryStats
    topics: TopicStats
    scheduler: SchedulerStats
    system: SystemStats


# ── 端点 ──────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=StatusOverviewResponse,
    summary="系统状态概览",
    description="聚合返回推文、关注、摘要、主题、调度器和系统维度的关键指标。",
)
async def get_status_overview(
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StatusOverviewResponse:
    """获取系统状态概览。"""
    tweets = await _get_tweet_stats(session)
    follows = await _get_follow_stats(session)
    summaries = await _get_summary_stats(session)
    topics = await _get_topic_stats(session)
    scheduler = _get_scheduler_stats()
    system = _get_system_stats()

    return StatusOverviewResponse(
        tweets=tweets,
        follows=follows,
        summaries=summaries,
        topics=topics,
        scheduler=scheduler,
        system=system,
    )


# ── 查询辅助函数 ──────────────────────────────────────────


async def _get_tweet_stats(session: AsyncSession) -> TweetStats:
    """推文统计。"""
    total_result = await session.execute(select(func.count()).select_from(TweetOrm))
    total = total_result.scalar() or 0

    latest_result = await session.execute(select(func.max(TweetOrm.created_at)))
    latest_tweet_at = latest_result.scalar()

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_result = await session.execute(
        select(func.count())
        .select_from(TweetOrm)
        .where(TweetOrm.created_at >= today_start)
    )
    today_count = today_result.scalar() or 0

    return TweetStats(
        total=total,
        latest_tweet_at=latest_tweet_at,
        today_count=today_count,
    )


async def _get_follow_stats(session: AsyncSession) -> FollowStats:
    """关注账号统计。"""
    total_result = await session.execute(
        select(func.count()).select_from(ScraperFollow)
    )
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
    total_result = await session.execute(
        select(func.count()).select_from(SummaryOrm)
    )
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


async def _get_topic_stats(session: AsyncSession) -> TopicStats:
    """主题统计。"""
    total_result = await session.execute(select(func.count()).select_from(TopicOrm))
    total = total_result.scalar() or 0

    # 最近一次主题摘要任务
    latest_task_result = await session.execute(
        select(TopicSummaryTaskOrm.completed_at, TopicSummaryTaskOrm.status)
        .order_by(TopicSummaryTaskOrm.created_at.desc())
        .limit(1)
    )
    latest_task = latest_task_result.first()

    latest_summary_at = latest_task.completed_at if latest_task else None
    latest_summary_status = latest_task.status if latest_task else None

    return TopicStats(
        total=total,
        latest_summary_at=latest_summary_at,
        latest_summary_status=latest_summary_status,
    )


def _get_scheduler_stats() -> SchedulerStats:
    """调度器统计。"""
    scheduler = get_scheduler()

    if scheduler is not None and scheduler.running:
        status = "running"
        job = scheduler.get_job("scraper_job")
        next_run_time = job.next_run_time if job else None
    else:
        status = "stopped"
        next_run_time = None

    # 从 settings 获取默认间隔
    settings = get_settings()
    interval_seconds = settings.scraper_interval

    return SchedulerStats(
        status=status,
        next_run_time=next_run_time,
        interval_seconds=interval_seconds,
    )


def _get_system_stats() -> SystemStats:
    """系统统计。"""
    server_start_time = get_server_start_time()

    # 数据库大小（仅 SQLite）
    database_size_mb = None
    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        # 处理相对路径的 ./
        if db_path.startswith("./"):
            db_path = db_path[2:]
        try:
            size_bytes = os.path.getsize(db_path)
            database_size_mb = round(size_bytes / (1024 * 1024), 2)
        except OSError:
            database_size_mb = None

    return SystemStats(
        server_start_time=server_start_time,
        database_size_mb=database_size_mb,
    )
