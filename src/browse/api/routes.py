"""Browse API 路由。

提供推文浏览相关的 HTTP 端点：每日统计、作者列表、推文列表。
"""

import logging
import math
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.browse.api.schemas import (
    AuthorInfo,
    AuthorListResponse,
    BrowseTweetItem,
    BrowseTweetListResponse,
    DailyCount,
    DailyStatsResponse,
)
from src.browse.services.browse_service import BrowseService
from src.database.async_session import get_db_session
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browse", tags=["browse"])

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get(
    "/stats/daily",
    response_model=DailyStatsResponse,
    summary="获取每日推文统计",
)
async def get_daily_stats(
    year: int = Query(..., description="年份"),
    month: int = Query(..., ge=1, le=12, description="月份（1-12）"),
    tz_offset: int = Query(0, ge=-720, le=840, description="时区偏移（分钟），来自 JS getTimezoneOffset()"),
    min_text_length: int | None = Query(None, ge=1, description="最小推文长度（字符数）"),
    _admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_db_session),
) -> DailyStatsResponse:
    """按年月查询该月内每天的推文数量（按用户本地时区分组）。"""
    try:
        service = BrowseService(session)
        days = await service.get_daily_stats(year, month, tz_offset, min_text_length)
        return DailyStatsResponse(
            year=year,
            month=month,
            days=[DailyCount(**d) for d in days],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("每日统计查询失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误",
        ) from e


@router.get(
    "/authors",
    response_model=AuthorListResponse,
    summary="获取作者列表",
)
async def get_authors(
    date: str = Query(..., description="日期，YYYY-MM-DD 格式"),
    tz_offset: int = Query(0, ge=-720, le=840, description="时区偏移（分钟），来自 JS getTimezoneOffset()"),
    min_text_length: int | None = Query(None, ge=1, description="最小推文长度（字符数）"),
    _admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuthorListResponse:
    """查询指定日期有推文的所有作者。"""
    if not DATE_PATTERN.match(date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="无效的日期格式，需要 YYYY-MM-DD",
        )

    try:
        service = BrowseService(session)
        authors = await service.get_authors(date, tz_offset, min_text_length)
        return AuthorListResponse(
            authors=[AuthorInfo(**a) for a in authors],
            total=len(authors),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("作者列表查询失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误",
        ) from e


@router.get(
    "/tweets",
    response_model=BrowseTweetListResponse,
    summary="获取推文浏览列表",
)
async def get_tweets(
    date: str = Query(..., description="日期，YYYY-MM-DD 格式"),
    author: str | None = Query(None, description="作者用户名筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tz_offset: int = Query(0, ge=-720, le=840, description="时区偏移（分钟），来自 JS getTimezoneOffset()"),
    min_text_length: int | None = Query(None, ge=1, description="最小推文长度（字符数）"),
    _admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_db_session),
) -> BrowseTweetListResponse:
    """查询指定日期（可选作者）的推文列表，含摘要和翻译。"""
    if not DATE_PATTERN.match(date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="无效的日期格式，需要 YYYY-MM-DD",
        )

    try:
        service = BrowseService(session)
        items, total = await service.get_tweets(date, author, page, page_size, tz_offset, min_text_length)
        total_pages = math.ceil(total / page_size) if total > 0 else 0

        return BrowseTweetListResponse(
            items=[BrowseTweetItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("推文浏览查询失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误",
        ) from e
