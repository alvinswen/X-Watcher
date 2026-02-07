"""摘要 API 路由。

提供摘要相关的 HTTP API 端点。
"""

import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

from src.database.async_session import get_async_session_maker
from src.scraper import TaskRegistry, TaskStatus
from src.summarization.api.schemas import (
    BatchSummaryRequest,
    BatchSummaryResponse,
    CostStatsResponse,
    ErrorResponse,
    SummaryResponse,
    SummaryResultResponse,
)
from src.summarization.domain.models import PromptConfig
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.services.summarization_service import (
    SummarizationService,
    create_summarization_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summaries", tags=["summaries"])

# 全局任务注册表
_task_registry: TaskRegistry | None = None


def get_task_registry() -> TaskRegistry:
    """获取任务注册表实例。"""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry.get_instance()
    return _task_registry


# ========== 后台任务函数 ==========


def _run_summarization_task(
    task_id: str,
    tweet_ids: list[str],
    force_refresh: bool,
) -> None:
    """在后台运行摘要任务。

    Args:
        task_id: 任务 ID
        tweet_ids: 推文 ID 列表
        force_refresh: 是否强制刷新缓存
    """
    registry = get_task_registry()
    loop = None

    async def _execute() -> None:
        try:
            # 创建数据库会话
            session_maker = get_async_session_maker()
            async with session_maker() as session:
                # 创建仓储
                repository = SummarizationRepository(session)

                # 加载 LLM 配置
                config = LLMProviderConfig.from_env()

                # 创建摘要服务
                service = create_summarization_service(
                    repository=repository,
                    config=config,
                    prompt_config=PromptConfig(),
                )

                # 执行摘要
                result = await service.summarize_tweets(
                    tweet_ids=tweet_ids,
                    force_refresh=force_refresh,
                )

                # 检查结果类型
                from returns.result import Failure

                if isinstance(result, Failure):
                    error = result.failure()
                    raise error

                summary_result = result.unwrap()

                # 更新任务状态
                registry.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    result={
                        "total_tweets": summary_result.total_tweets,
                        "total_groups": summary_result.total_groups,
                        "cache_hits": summary_result.cache_hits,
                        "cache_misses": summary_result.cache_misses,
                        "total_tokens": summary_result.total_tokens,
                        "total_cost_usd": summary_result.total_cost_usd,
                        "providers_used": summary_result.providers_used,
                        "processing_time_ms": summary_result.processing_time_ms,
                    },
                )

                await session.commit()

        except Exception as e:
            logger.exception(f"后台摘要任务执行失败: {e}")
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
    response_model=BatchSummaryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "无效输入"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def start_batch_summarization(
    request: BatchSummaryRequest,
    background_tasks: BackgroundTasks,
) -> BatchSummaryResponse:
    """启动批量摘要任务。

    对指定的推文列表执行摘要和翻译，返回任务 ID 用于查询进度。

    Args:
        request: 批量摘要请求
        background_tasks: FastAPI 后台任务管理器

    Returns:
        BatchSummaryResponse: 包含任务 ID 和状态的响应
    """
    registry = get_task_registry()

    # 创建任务
    task_id = registry.create_task(
        task_name=f"摘要 {len(request.tweet_ids)} 条推文",
        metadata={
            "tweet_count": len(request.tweet_ids),
            "tweet_ids": request.tweet_ids[:10],  # 只记录前 10 个
            "force_refresh": request.force_refresh,
        },
    )

    # 添加后台任务
    background_tasks.add_task(
        _run_summarization_task,
        task_id,
        request.tweet_ids,
        request.force_refresh,
    )

    logger.info(
        f"创建摘要任务: {task_id} - {len(request.tweet_ids)} 条推文, "
        f"force_refresh={request.force_refresh}"
    )

    return BatchSummaryResponse(task_id=task_id, status="pending")


@router.get(
    "/tweets/{tweet_id}",
    response_model=SummaryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "摘要不存在"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def get_tweet_summary(tweet_id: str) -> SummaryResponse:
    """查询单条推文的摘要。

    Args:
        tweet_id: 推文 ID

    Returns:
        SummaryResponse: 摘要详情

    Raises:
        HTTPException: 404 摘要不存在
    """
    session_maker = get_async_session_maker()

    try:
        async with session_maker() as session:
            repository = SummarizationRepository(session)
            summary = await repository.get_summary_by_tweet(tweet_id)

            if summary is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"推文摘要不存在: {tweet_id}",
                )

            return SummaryResponse.from_domain(summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询推文摘要失败 (tweet_id={tweet_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get(
    "/stats",
    response_model=CostStatsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "无效的日期范围"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def get_cost_statistics(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> CostStatsResponse:
    """查询成本统计。

    支持按日期范围筛选成本统计。

    Args:
        start_date: 统计开始日期（可选，ISO 8601 格式）
        end_date: 统计结束日期（可选，ISO 8601 格式）

    Returns:
        CostStatsResponse: 成本统计结果

    Raises:
        HTTPException: 400 无效的日期范围
    """
    # 验证日期范围
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date 不能晚于 end_date",
        )

    session_maker = get_async_session_maker()

    try:
        async with session_maker() as session:
            repository = SummarizationRepository(session)
            stats = await repository.get_cost_stats(start_date, end_date)

            return CostStatsResponse(
                start_date=stats.start_date,
                end_date=stats.end_date,
                total_cost_usd=stats.total_cost_usd,
                total_tokens=stats.total_tokens,
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                provider_breakdown=stats.provider_breakdown,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取成本统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.post(
    "/tweets/{tweet_id}/regenerate",
    response_model=SummaryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "推文不存在或未找到去重组"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def regenerate_tweet_summary(tweet_id: str) -> SummaryResponse:
    """强制重新生成推文摘要。

    忽略缓存，重新调用 LLM 生成摘要和翻译。

    Args:
        tweet_id: 推文 ID

    Returns:
        SummaryResponse: 新生成的摘要

    Raises:
        HTTPException: 404 推文不存在，500 生成失败
    """
    session_maker = get_async_session_maker()

    try:
        async with session_maker() as session:
            repository = SummarizationRepository(session)

            # 加载 LLM 配置
            config = LLMProviderConfig.from_env()

            # 创建摘要服务
            service = create_summarization_service(
                repository=repository,
                config=config,
                prompt_config=PromptConfig(),
            )

            # 重新生成摘要
            result = await service.regenerate_summary(tweet_id)

            from returns.result import Failure

            if isinstance(result, Failure):
                error = result.failure()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"重新生成摘要失败: {error}",
                )

            summary = result.unwrap()

            await session.commit()

            return SummaryResponse.from_domain(summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新生成摘要失败 (tweet_id={tweet_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get(
    "/tasks/{task_id}",
    responses={
        404: {"model": ErrorResponse, "description": "任务不存在"},
    },
)
async def get_summarization_task_status(task_id: str) -> dict:
    """查询摘要任务状态。

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


@router.delete("/tasks/{task_id}")
async def delete_summarization_task(task_id: str) -> dict:
    """删除摘要任务。

    删除已完成的任务记录。正在运行的任务不能被删除。

    Args:
        task_id: 任务 ID

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 404 任务不存在，409 任务正在运行
    """
    registry = get_task_registry()
    task_data = registry.get_task_status(task_id)

    if task_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )

    if task_data["status"] == TaskStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能删除正在运行的任务",
        )

    deleted = registry.delete_task(task_id)

    if deleted:
        logger.info(f"删除摘要任务: {task_id}")
        return {"message": f"任务 {task_id} 已删除"}

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="删除任务失败",
    )
