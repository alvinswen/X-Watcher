"""推文 API 路由。

提供推文列表和详情查询的 HTTP API 端点。
"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_db_session
from src.scraper.infrastructure.models import TweetOrm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tweets", tags=["tweets"])


# ========== 响应模型 ==========


class TweetListItem(BaseModel):
    """推文列表项响应模型。"""

    tweet_id: str = Field(..., description="推文 ID")
    text: str = Field(..., description="推文内容")
    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    created_at: datetime = Field(..., description="推文创建时间")
    reference_type: str | None = Field(None, description="引用类型")
    referenced_tweet_id: str | None = Field(None, description="引用的推文 ID")
    has_summary: bool = Field(False, description="是否有摘要")
    has_deduplication: bool = Field(False, description="是否去重")
    media_count: int = Field(0, description="媒体数量")


class TweetDetailResponse(TweetListItem):
    """推文详情响应模型。"""

    media: list[dict] | None = Field(None, description="媒体附件")
    summary: dict | None = Field(None, description="摘要信息")
    deduplication: dict | None = Field(None, description="去重信息")


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
    session: AsyncSession = Depends(get_db_session),
) -> TweetListResponse:
    """获取推文列表。

    支持分页和按作者筛选，按创建时间倒序排列。

    Args:
        page: 页码（从 1 开始）
        page_size: 每页数量（1-100）
        author: 可选的作者用户名筛选
        session: 数据库会话（依赖注入）

    Returns:
        TweetListResponse: 推文列表响应
    """
    try:
        # 导入 SQLAlchemy 组件
        from sqlalchemy import case, func, select

        from src.summarization.infrastructure.models import SummaryOrm

        # 构建 ORM 查询，使用 LEFT JOIN 检查摘要存在性
        stmt = (
            select(
                TweetOrm.tweet_id,
                TweetOrm.text,
                TweetOrm.created_at,
                TweetOrm.author_username,
                TweetOrm.author_display_name,
                TweetOrm.referenced_tweet_id,
                TweetOrm.reference_type,
                TweetOrm.media,
                TweetOrm.db_created_at,
                TweetOrm.db_updated_at,
                # 使用 CASE 语句检查摘要是否存在
                case((SummaryOrm.summary_id.isnot(None), True), else_=False).label(
                    "has_summary"
                ),
            )
            .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
        )

        # 添加作者筛选
        if author:
            stmt = stmt.where(TweetOrm.author_username == author)

        # 计算总数
        count_stmt = select(func.count()).select_from(TweetOrm)
        if author:
            count_stmt = count_stmt.where(TweetOrm.author_username == author)

        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        # 添加排序和分页
        stmt = stmt.order_by(TweetOrm.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        # 执行查询
        result = await session.execute(stmt)
        rows = result.fetchall()

        # 构建响应
        items = []
        for row in rows:
            tweet_dict = dict(row._mapping)
            # 统计媒体数量
            media = tweet_dict.get("media")
            media_count = len(media) if media else 0

            # 从查询结果获取 has_summary（EXISTS 子查询的结果）
            has_summary = bool(tweet_dict.get("has_summary", False))

            items.append(
                TweetListItem(
                    tweet_id=tweet_dict["tweet_id"],
                    text=tweet_dict["text"],
                    author_username=tweet_dict["author_username"],
                    author_display_name=tweet_dict.get("author_display_name"),
                    created_at=tweet_dict["created_at"],
                    reference_type=tweet_dict.get("reference_type"),
                    referenced_tweet_id=tweet_dict.get("referenced_tweet_id"),
                    has_summary=has_summary,
                    has_deduplication=False,  # 暂不查询去重状态
                    media_count=media_count,
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
    session: AsyncSession = Depends(get_db_session),
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
        # 查询推文 - 只选择必要的列
        from sqlalchemy import select

        stmt = select(
            TweetOrm.tweet_id,
            TweetOrm.text,
            TweetOrm.created_at,
            TweetOrm.author_username,
            TweetOrm.author_display_name,
            TweetOrm.referenced_tweet_id,
            TweetOrm.reference_type,
            TweetOrm.media,
        ).where(TweetOrm.tweet_id == tweet_id)

        result = await session.execute(stmt)
        row = result.first()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"推文不存在: {tweet_id}",
            )

        tweet_dict = {
            "tweet_id": row.tweet_id,
            "text": row.text,
            "author_username": row.author_username,
            "author_display_name": row.author_display_name,
            "created_at": row.created_at,
            "reference_type": row.reference_type,
            "referenced_tweet_id": row.referenced_tweet_id,
            "media": row.media,
            "has_summary": False,
            "has_deduplication": False,  # 暂不查询去重状态
            "media_count": len(row.media) if row.media else 0,
        }

        # 查询摘要信息
        summary = None
        try:
            from src.summarization.infrastructure.repository import SummarizationRepository

            summary_repo = SummarizationRepository(session)
            summary_record = await summary_repo.get_summary_by_tweet(tweet_id)

            if summary_record:
                summary = {
                    "summary_id": summary_record.summary_id,
                    "summary_text": summary_record.summary_text,
                    "translation_text": summary_record.translation_text,
                    "model_provider": summary_record.model_provider,
                    "model_name": summary_record.model_name,
                    "cost_usd": summary_record.cost_usd,
                    "cached": summary_record.cached,
                    "is_generated_summary": summary_record.is_generated_summary,
                    "created_at": summary_record.created_at.isoformat()
                    if summary_record.created_at
                    else None,
                }
                tweet_dict["has_summary"] = True
        except Exception as e:
            logger.warning(f"查询摘要信息失败: {e}")

        # 查询去重信息（暂时跳过，因为需要 deduplication_group_id 列）
        deduplication = None
        # TODO: 在数据库迁移后，可以通过查询 deduplication_groups 表获取去重信息

        return TweetDetailResponse(
            **tweet_dict,
            summary=summary,
            deduplication=deduplication,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询推文详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
