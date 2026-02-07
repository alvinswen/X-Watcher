"""去重 API 路由。

提供去重相关的 HTTP API 端点。
"""

import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from src.database.async_session import get_async_session_maker
from src.deduplication.domain.models import (
    DeduplicationConfig,
    DeduplicationGroup,
    DeduplicationResult,
)
from src.deduplication.infrastructure.repository import DeduplicationRepository
from src.deduplication.services.deduplication_service import DeduplicationService
from src.deduplication.domain.detectors import ExactDuplicateDetector, SimilarityDetector
from src.scraper import TaskRegistry, TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deduplicate", tags=["deduplication"])

# 全局任务注册表
_task_registry: TaskRegistry | None = None


def get_task_registry() -> TaskRegistry:
    """获取任务注册表实例。"""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry.get_instance()
    return _task_registry


# ========== 请求/响应模型 ==========


class DeduplicateRequest(BaseModel):
    """去重请求模型。"""

    tweet_ids: list[str] = Field(..., min_length=1, description="推文 ID 列表")
    config: DeduplicationConfig | None = Field(None, description="去重配置")

    @field_validator("tweet_ids")
    @classmethod
    def validate_tweet_ids(cls, v: list[str]) -> list[str]:
        """验证推文 ID 列表。"""
        if not v:
            raise ValueError("tweet_ids 不能为空")
        if len(v) > 10000:
            raise ValueError("tweet_ids 数量不能超过 10000")
        return v


class DeduplicateResponse(BaseModel):
    """去重响应模型。"""

    task_id: str = Field(..., description="任务 ID")
    status: Literal["pending", "running", "completed", "failed"] = Field(
        ..., description="任务状态"
    )


class DeduplicationGroupResponse(BaseModel):
    """去重组响应模型。"""

    group_id: str = Field(..., description="去重组 ID")
    representative_tweet_id: str = Field(..., description="代表推文 ID")
    deduplication_type: str = Field(..., description="去重类型")
    similarity_score: float | None = Field(None, description="相似度分数")
    tweet_ids: list[str] = Field(..., description="组内推文 ID 列表")
    created_at: datetime = Field(..., description="创建时间")

    @classmethod
    def from_domain(cls, group: DeduplicationGroup) -> "DeduplicationGroupResponse":
        """从领域模型创建响应。"""
        return cls(
            group_id=group.group_id,
            representative_tweet_id=group.representative_tweet_id,
            deduplication_type=group.deduplication_type.value,
            similarity_score=group.similarity_score,
            tweet_ids=group.tweet_ids,
            created_at=group.created_at,
        )


class ErrorResponse(BaseModel):
    """错误响应模型。"""

    detail: str = Field(..., description="错误详情")


# ========== 后台任务函数 ==========


def _run_deduplication_task(
    task_id: str,
    tweet_ids: list[str],
    config: DeduplicationConfig | None,
) -> None:
    """在后台运行去重任务。

    Args:
        task_id: 任务 ID
        tweet_ids: 推文 ID 列表
        config: 去重配置
    """
    registry = get_task_registry()
    loop = None

    async def _execute() -> None:
        try:
            # 创建数据库会话
            session_maker = get_async_session_maker()
            async with session_maker() as session:
                # 创建仓库和服务
                repository = DeduplicationRepository(session)
                service = DeduplicationService(
                    repository=repository,
                    exact_detector=ExactDuplicateDetector(),
                    similarity_detector=SimilarityDetector(),
                )

                # 执行去重
                result = await service.deduplicate_tweets(
                    tweet_ids=tweet_ids,
                    config=config,
                )

                # 更新任务状态
                registry.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    result={
                        "total_tweets": result.total_tweets,
                        "exact_duplicate_count": result.exact_duplicate_count,
                        "similar_content_count": result.similar_content_count,
                        "affected_tweets": result.affected_tweets,
                        "preserved_tweets": result.preserved_tweets,
                        "elapsed_seconds": result.elapsed_seconds,
                    },
                )

                await session.commit()

        except Exception as e:
            logger.exception(f"后台去重任务执行失败: {e}")
            registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_execute())
    except Exception as e:
        logger.exception(f"后台任务执行异常: {e}")
        registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
    finally:
        if loop:
            loop.close()


# ========== API 端点 ==========


@router.post(
    "/batch",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "无效输入"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def start_deduplication(
    request: DeduplicateRequest,
    background_tasks: BackgroundTasks,
) -> DeduplicateResponse:
    """启动批量去重任务。

    对指定的推文列表执行去重，返回任务 ID 用于查询进度。

    Args:
        request: 去重请求
        background_tasks: FastAPI 后台任务管理器

    Returns:
        DeduplicateResponse: 包含任务 ID 和状态的响应
    """
    registry = get_task_registry()

    # 创建任务
    task_id = registry.create_task(
        task_name=f"去重 {len(request.tweet_ids)} 条推文",
        metadata={
            "tweet_count": len(request.tweet_ids),
            "tweet_ids": request.tweet_ids[:10],  # 只记录前 10 个
        },
    )

    # 添加后台任务
    background_tasks.add_task(
        _run_deduplication_task,
        task_id,
        request.tweet_ids,
        request.config,
    )

    logger.info(f"创建去重任务: {task_id} - {len(request.tweet_ids)} 条推文")

    return DeduplicateResponse(task_id=task_id, status="pending")


@router.get(
    "/groups/{group_id}",
    responses={
        404: {"model": ErrorResponse, "description": "去重组不存在"},
    },
)
async def get_deduplication_group(group_id: str) -> DeduplicationGroupResponse:
    """查询去重组详情。

    Args:
        group_id: 去重组 ID

    Returns:
        DeduplicationGroupResponse: 去重组详情

    Raises:
        HTTPException: 404 去重组不存在
    """
    session_maker = get_async_session_maker()

    async with session_maker() as session:
        repository = DeduplicationRepository(session)
        group = await repository.get_group(group_id)

        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"去重组不存在: {group_id}",
            )

        return DeduplicationGroupResponse.from_domain(group)


@router.get(
    "/tweets/{tweet_id}",
    responses={
        404: {"model": ErrorResponse, "description": "推文不存在或未去重"},
    },
)
async def get_tweet_deduplication(tweet_id: str) -> DeduplicationGroupResponse:
    """查询推文的去重状态。

    Args:
        tweet_id: 推文 ID

    Returns:
        DeduplicationGroupResponse: 去重组详情

    Raises:
        HTTPException: 404 推文不存在或未去重
    """
    session_maker = get_async_session_maker()

    async with session_maker() as session:
        repository = DeduplicationRepository(session)
        group = await repository.find_by_tweet(tweet_id)

        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"推文不存在或未去重: {tweet_id}",
            )

        return DeduplicationGroupResponse.from_domain(group)


@router.delete(
    "/groups/{group_id}",
    responses={
        404: {"model": ErrorResponse, "description": "去重组不存在"},
        409: {"model": ErrorResponse, "description": "冲突"},
    },
)
async def delete_deduplication_group(group_id: str) -> dict[str, str]:
    """删除去重组（撤销去重）。

    Args:
        group_id: 去重组 ID

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 404 去重组不存在，409 冲突
    """
    session_maker = get_async_session_maker()

    try:
        async with session_maker() as session:
            repository = DeduplicationRepository(session)
            await repository.delete_group(group_id)
            await session.commit()

        logger.info(f"删除去重组: {group_id}")
        return {"message": f"去重组 {group_id} 已删除"}

    except Exception as e:
        if "不存在" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get("/tasks/{task_id}")
async def get_deduplication_task_status(task_id: str) -> dict:
    """查询去重任务状态。

    Args:
        task_id: 任务 ID

    Returns:
        dict: 任务状态详情

    Raises:
        HTTPException: 404 任务不存在
    """
    registry = get_task_registry()
    task_data = registry.get_task_status(task_id)

    if task_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )

    return {
        "task_id": task_data["task_id"],
        "status": task_data["status"],
        "result": task_data.get("result"),
        "error": task_data.get("error"),
        "created_at": task_data.get("created_at"),
        "started_at": task_data.get("started_at"),
        "completed_at": task_data.get("completed_at"),
        "progress": task_data.get("progress"),
        "metadata": task_data.get("metadata"),
    }
