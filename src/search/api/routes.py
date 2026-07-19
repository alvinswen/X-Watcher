"""搜索 API 路由。"""

import logging
import math
from datetime import datetime, timezone, UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.data_layer.provider import get_search_repo
from src.search.api.schemas import SearchResponse, SearchTweetItem
from src.shared.error_messages import SEARCH_TIME_FORMAT_INVALID_TMPL
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


def _parse_time_param(name: str, raw: str) -> datetime:
    """解析搜索时间参数并保留原有 naive→UTC 语义。"""
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=SEARCH_TIME_FORMAT_INVALID_TMPL.format(name=name, value=raw),
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@router.get(
    "/tweets",
    response_model=SearchResponse,
    summary="搜索推文",
    description="按关键词搜索推文，支持多关键词 AND 逻辑、作者筛选和时间范围过滤。",
)
async def search_tweets(
    q: str = Query(..., min_length=1, description="搜索关键词（空格分隔多词为 AND 逻辑）"),
    author: str | None = Query(None, description="按作者用户名筛选（大小写不敏感）"),
    authors: str | None = Query(None, description="按多个作者筛选（逗号分隔，大小写不敏感）"),
    since: str | None = Query(None, description="起始时间（含），ISO 8601 格式"),
    until: str | None = Query(None, description="截止时间（不含），ISO 8601 格式"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    include_summary: bool = Query(True, description="是否包含摘要和翻译"),
    current_user: UserDomain = Depends(get_current_user),
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

    parsed_since = None
    parsed_until = None
    if since:
        parsed_since = _parse_time_param("since", since)
    if until:
        parsed_until = _parse_time_param("until", until)

    if parsed_since and parsed_until and parsed_since >= parsed_until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="时间区间无效: since 必须早于 until",
        )

    try:
        result = await get_search_repo().search_tweets(
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
