"""搜索 API 路由。"""

import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_db_session
from src.search.api.schemas import SearchResponse, SearchTweetItem
from src.search.services.search_service import SearchService
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get(
    "/tweets",
    response_model=SearchResponse,
    summary="搜索推文",
    description="按关键词搜索推文，支持多关键词 AND 逻辑、作者筛选和时间范围过滤。",
)
async def search_tweets(
    q: str = Query(..., min_length=1, description="搜索关键词（空格分隔多词为 AND 逻辑）"),
    author: str | None = Query(None, description="按作者用户名筛选（大小写不敏感）"),
    authors: str | None = Query(
        None, description="按多个作者筛选（逗号分隔，大小写不敏感）"
    ),
    since: str | None = Query(None, description="起始时间（含），ISO 8601 格式"),
    until: str | None = Query(None, description="截止时间（不含），ISO 8601 格式"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    include_summary: bool = Query(True, description="是否包含摘要和翻译"),
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    """搜索推文。"""
    # author 和 authors 互斥
    if author and authors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="author 和 authors 参数不能同时使用",
        )

    # authors 字符串转列表
    authors_list: list[str] | None = None
    if authors:
        authors_list = [a.strip() for a in authors.split(",") if a.strip()]
        if not authors_list:
            authors_list = None

    # 解析时间参数
    from datetime import datetime, timezone

    parsed_since = None
    parsed_until = None
    try:
        if since:
            parsed_since = datetime.fromisoformat(since)
            if parsed_since.tzinfo is None:
                parsed_since = parsed_since.replace(tzinfo=timezone.utc)
        if until:
            parsed_until = datetime.fromisoformat(until)
            if parsed_until.tzinfo is None:
                parsed_until = parsed_until.replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"时间格式无效: {e}",
        )

    if parsed_since and parsed_until and parsed_since >= parsed_until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="时间区间无效: since 必须早于 until",
        )

    try:
        service = SearchService(session)
        result = await service.search_tweets(
            q=q,
            page=page,
            page_size=page_size,
            include_summary=include_summary,
            author=author,
            authors=authors_list,
            since=parsed_since,
            until=parsed_until,
        )

        items = [SearchTweetItem(**item) for item in result.items]
        total_pages = math.ceil(result.total / page_size) if result.total > 0 else 0

        return SearchResponse(
            items=items,
            count=len(items),
            total=result.total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            q=q,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("搜索失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误",
        ) from e
