"""Analytics API 路由。

包含发文频次分析（用户级别）端点。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.api.schemas import (
    FrequencySlotResponse,
    PostingFrequencyResponse,
    TimeRangeResponse,
)
from src.analytics.services.analytics_service import AnalyticsService
from src.database.async_session import get_db_session
from src.topic.infrastructure.models import TopicOrm
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)


# ── 发文频次分析路由（用户级别，非 admin-only） ──────────────────────

analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@analytics_router.get(
    "/topics/{topic_id}/posting-frequency",
    response_model=PostingFrequencyResponse,
)
async def get_posting_frequency(
    topic_id: int,
    tz_offset: int = Query(default=0),
    slots: int = Query(default=50, ge=1, le=336),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    """获取主题下所有关联账号的发文频次分布。"""
    # 1. 查询主题
    result = await session.execute(
        select(TopicOrm).where(TopicOrm.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在"
        )

    # 2. 所有权检查：admin 可访问所有，非 admin 只能访问自己的主题
    if not current_user.is_admin and topic.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该主题"
        )

    # 3. 调用 Service 获取数据
    service = AnalyticsService(session)
    data = await service.get_posting_frequency(
        topic_id=topic_id, tz_offset=tz_offset, slots=slots
    )

    # 4. 包装响应
    return PostingFrequencyResponse(
        topic_id=topic_id,
        topic_name=topic.name,
        slot_minutes=30,
        slots=slots,
        tz_offset=tz_offset,
        time_range=TimeRangeResponse(
            start=data["time_range_start"].isoformat(),
            end=data["time_range_end"].isoformat(),
        ),
        distribution=[
            FrequencySlotResponse(slot=d["slot"], count=d["count"])
            for d in data["distribution"]
        ],
        total_tweets=data["total_tweets"],
    )
