"""Feed API 路由。

提供按时间区间查询推文的 HTTP 端点，支持认证和摘要加载。
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.async_session import get_db_session
from src.feed.api.schemas import FeedResponse, FeedTweetItem
from src.feed.services.feed_service import FeedService
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get(
    "",
    response_model=FeedResponse,
    summary="获取推文 Feed",
    description="按时间区间查询推文列表，支持增量拉取，返回完整内容含摘要和翻译。",
)
async def get_feed(
    since: datetime = Query(
        ..., description="起始时间（ISO 8601 格式），过滤 db_created_at >= since"
    ),
    until: datetime | None = Query(
        None, description="截止时间（ISO 8601 格式），默认当前服务器时间"
    ),
    limit: int | None = Query(None, ge=1, description="最大返回条数"),
    include_summary: bool = Query(True, description="是否包含摘要和翻译"),
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> FeedResponse:
    """获取指定时间区间内的推文列表。"""
    try:
        settings = get_settings()

        # 处理默认值
        actual_until = until if until is not None else datetime.now(timezone.utc)

        # 统一时区：确保 since 和 actual_until 都是 aware 或都是 naive
        if since.tzinfo is not None and actual_until.tzinfo is None:
            actual_until = actual_until.replace(tzinfo=timezone.utc)
        elif since.tzinfo is None and actual_until.tzinfo is not None:
            since = since.replace(tzinfo=timezone.utc)

        # 处理 limit：未提供或超过系统配置上限时，使用配置值
        max_limit = settings.feed_max_tweets
        if limit is None or limit > max_limit:
            actual_limit = max_limit
        else:
            actual_limit = limit

        # 验证时间区间
        if since >= actual_until:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="时间区间无效: since 必须早于 until",
            )

        # 执行查询
        service = FeedService(session)
        result = await service.get_feed(
            since=since,
            until=actual_until,
            limit=actual_limit,
            include_summary=include_summary,
        )

        # 构建响应
        items = [FeedTweetItem(**item) for item in result.items]

        return FeedResponse(
            items=items,
            count=result.count,
            total=result.total,
            since=since,
            until=actual_until,
            has_more=result.has_more,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Feed 查询失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误",
        ) from e
