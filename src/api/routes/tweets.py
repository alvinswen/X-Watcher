"""推文 API 路由。

提供推文列表和详情查询的 HTTP API 端点。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.shared.schemas import UTCDatetimeModel
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tweets", tags=["tweets"])


# ========== 响应模型 ==========


class TweetListItem(UTCDatetimeModel):
    """推文列表项响应模型。"""

    tweet_id: str = Field(..., description="推文 ID")
    text: str = Field(..., description="推文内容")
    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    created_at: datetime = Field(..., description="推文创建时间")
    db_created_at: datetime = Field(..., description="入库时间")
    reference_type: str | None = Field(None, description="引用类型")
    referenced_tweet_id: str | None = Field(None, description="引用的推文 ID")
    has_summary: bool = Field(False, description="是否有摘要")
    media_count: int = Field(0, description="媒体数量")


class TweetDetailResponse(TweetListItem):
    """推文详情响应模型。"""

    media: list[dict[str, Any]] | None = Field(None, description="媒体附件")
    summary: dict[str, Any] | None = Field(None, description="摘要信息")


class TweetListResponse(BaseModel):
    """推文列表响应模型。"""

    items: list[TweetListItem] = Field(..., description="推文列表")
    total: int = Field(..., description="总数量")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    total_pages: int = Field(..., description="总页数")


class ErrorResponse(BaseModel):
    """错误响应模型。"""

    detail: str = Field(..., description="错误详情")


# ========== 辅助函数 ==========


def _ensure_utc(dt: datetime) -> datetime:
    """将 naive datetime 转换为 UTC aware datetime；已有时区信息则原样返回。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ========== API 端点 ==========


@router.get(
    "",
    response_model=TweetListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "无效输入"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def list_tweets(
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    author: str | None = Query(None, description="按作者用户名筛选"),
    created_after: datetime | None = Query(None, description="推文创建时间起始（含），ISO 8601 格式"),
    created_before: datetime | None = Query(None, description="推文创建时间截止（不含），ISO 8601 格式"),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> TweetListResponse:
    """获取推文列表。

    支持分页、按作者筛选和按创建时间范围筛选，按创建时间倒序排列。

    Args:
        page: 页码（从 1 开始）
        page_size: 每页数量（1-100）
        author: 可选的作者用户名筛选
        created_after: 可选的推文创建时间起始（含），ISO 8601 格式
        created_before: 可选的推文创建时间截止（不含），ISO 8601 格式
        session: 数据库会话（依赖注入）

    Returns:
        TweetListResponse: 推文列表响应
    """
    # 时间参数 UTC 标准化
    if created_after is not None:
        created_after = _ensure_utc(created_after)
    if created_before is not None:
        created_before = _ensure_utc(created_before)

    # 时间范围校验
    if created_after is not None and created_before is not None:
        if created_after >= created_before:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="时间范围无效: created_after 必须早于 created_before",
            )

    try:
        # 经数据层 provider 取 tweet 读门面(file/sqlalchemy 切换;pg 下线后 file-safe)
        from src.data_layer.provider import get_tweet_read_repo

        rows, total = await get_tweet_read_repo().list_tweets(
            page=page,
            page_size=page_size,
            author=author,
            created_after=created_after,
            created_before=created_before,
        )

        # 构建响应
        items = []
        for tweet_dict in rows:
            items.append(
                TweetListItem(
                    tweet_id=tweet_dict["tweet_id"],
                    text=tweet_dict["text"],
                    author_username=tweet_dict["author_username"],
                    author_display_name=tweet_dict.get("author_display_name"),
                    created_at=tweet_dict["created_at"],
                    db_created_at=tweet_dict["db_created_at"],
                    reference_type=tweet_dict.get("reference_type"),
                    referenced_tweet_id=tweet_dict.get("referenced_tweet_id"),
                    has_summary=bool(tweet_dict.get("has_summary", False)),
                    media_count=tweet_dict.get("media_count", 0),
                )
            )

        # 计算总页数
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        return TweetListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    except Exception as e:
        logger.error(f"查询推文列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get(
    "/{tweet_id}",
    response_model=TweetDetailResponse,
    responses={
        404: {"model": ErrorResponse, "description": "推文不存在"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def get_tweet_detail(
    tweet_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> TweetDetailResponse:
    """获取推文详情。

    返回推文的完整信息，包括摘要和去重信息。

    Args:
        tweet_id: 推文 ID
        session: 数据库会话（依赖注入）

    Returns:
        TweetDetailResponse: 推文详情响应

    Raises:
        HTTPException: 404 推文不存在
    """
    try:
        # 经数据层 provider 取 tweet 读门面(file/sqlalchemy 切换;pg 下线后 file-safe)
        from src.data_layer.provider import get_tweet_read_repo

        tweet_dict = await get_tweet_read_repo().get_tweet_detail(tweet_id)

        if tweet_dict is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"推文不存在: {tweet_id}",
            )

        # 查询摘要信息
        summary = None
        try:
            from src.data_layer.provider import get_summary_repo

            summary_repo = get_summary_repo()
            summary_record = await summary_repo.get_summary_by_tweet(tweet_id)

            if summary_record:
                def _utc_iso(dt: datetime | None) -> str | None:
                    if dt is None:
                        return None
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.isoformat()

                summary = {
                    "summary_id": summary_record.summary_id,
                    "summary_text": summary_record.summary_text,
                    "translation_text": summary_record.translation_text,
                    "model_provider": summary_record.model_provider,
                    "model_name": summary_record.model_name,
                    "cost_usd": summary_record.cost_usd,
                    "cached": summary_record.cached,
                    "is_generated_summary": summary_record.is_generated_summary,
                    "created_at": _utc_iso(summary_record.created_at),
                }
                tweet_dict["has_summary"] = True
        except Exception as e:
            logger.warning(f"查询摘要信息失败: {e}")

        return TweetDetailResponse(
            **tweet_dict,
            summary=summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询推文详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
