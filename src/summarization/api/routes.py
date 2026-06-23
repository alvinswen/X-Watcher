"""摘要 API 路由。

提供摘要相关的 HTTP API 端点。
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session_maker, get_db_session
from src.scraper import TaskRegistry, TaskStatus
from src.summarization.api.schemas import (
    BatchSummaryRequest,
    BatchSummaryResponse,
    CostStatsResponse,
    ErrorResponse,
    SummaryBackfillRequest,
    SummaryBackfillResponse,
    SummaryPreviewResponse,
    SummaryResetRequest,
    SummaryResetResponse,
    SummaryResponse,
)
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.summarization.domain.models import PromptConfig
from src.data_layer.provider import get_summary_repo, get_summarization_read_repo
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.services.summarization_service import (
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
    _admin: UserDomain = Depends(get_current_admin_user),
) -> BatchSummaryResponse:
    """启动批量摘要任务。

    对指定的推文列表执行摘要和翻译，返回任务 ID 用于查询进度。
    通过集中式摘要队列异步处理，支持优先级和背压。

    Args:
        request: 批量摘要请求

    Returns:
        BatchSummaryResponse: 包含任务 ID 和状态的响应
    """
    from src.summarization.services.summarization_queue import (
        SummarizationPriority,
        SummarizationQueue,
    )

    queue = SummarizationQueue.get_instance()
    task_id = await queue.enqueue(
        request.tweet_ids,
        force_refresh=request.force_refresh,
        source="batch_api",
        priority=SummarizationPriority.HIGH,
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
async def get_tweet_summary(
    tweet_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryResponse:
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
            repository = get_summary_repo(session)
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
    _admin: UserDomain = Depends(get_current_admin_user),
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
            repository = get_summary_repo(session)
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
async def regenerate_tweet_summary(
    tweet_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryResponse:
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
        # 加载 LLM 配置
        config = LLMProviderConfig.from_env()

        # 创建摘要服务（传入 session_factory，内部按需创建 session）
        service = create_summarization_service(
            session_factory=session_maker,
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
async def get_summarization_task_status(
    task_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict:
    """查询摘要任务状态（增强版）。

    包含分块进度、聚合结果和失败详情。
    当任务运行中时，还会返回实时分块进度 (live_progress)。

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

    response = {
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

    # 任务运行中时，从 ChunkTracker 获取实时分块进度
    task_status = task_data["status"]
    if isinstance(task_status, TaskStatus):
        is_active = task_status in (TaskStatus.PENDING, TaskStatus.RUNNING)
    else:
        is_active = task_status in ("pending", "running")

    if is_active:
        try:
            from src.summarization.services.summarization_queue import (
                SummarizationQueue,
            )

            queue = SummarizationQueue.get_instance()
            tracker = queue._task_chunk_trackers.get(task_id)
            if tracker is not None:
                response["live_progress"] = {
                    "total_chunks": tracker.total_chunks,
                    "completed_chunks": tracker.completed_chunks,
                    "failed_chunks": tracker.failed_chunks,
                    "total_tweets_requested": tracker.total_tweets_requested,
                    "total_tweets_summarized": tracker.total_tweets_summarized,
                    "total_cost_usd": round(tracker.total_cost_usd, 6),
                }
        except Exception:
            pass  # 获取实时进度失败不影响基本响应

    return response


@router.delete("/tasks/{task_id}")
async def delete_summarization_task(
    task_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict:
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


# ========== 摘要修复端点 ==========


@router.get(
    "/backfill/preview",
    response_model=SummaryPreviewResponse,
)
async def preview_backfill(
    since: datetime | None = Query(None, description="起始时间（含），ISO 8601 格式"),
    until: datetime | None = Query(None, description="截止时间（不含），ISO 8601 格式"),
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryPreviewResponse:
    """预览摘要补缺：查询缺少摘要的推文数量。"""
    count = await get_summarization_read_repo(session).count_unsummarized(
        since=since, until=until
    )
    return SummaryPreviewResponse(tweet_count=count)


@router.post(
    "/backfill",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SummaryBackfillResponse,
    responses={
        404: {"model": ErrorResponse, "description": "没有需要补缺的推文"},
    },
)
async def start_backfill(
    request: SummaryBackfillRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryBackfillResponse:
    """启动摘要补缺任务：为缺少摘要的推文生成摘要。

    通过集中式摘要队列异步处理，支持优先级和背压。
    """
    tweet_ids = await get_summarization_read_repo(session).list_unsummarized_ids(
        since=request.since, until=request.until
    )

    if not tweet_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="没有找到需要补缺的推文",
        )

    from src.summarization.services.summarization_queue import (
        SummarizationPriority,
        SummarizationQueue,
    )

    queue = SummarizationQueue.get_instance()
    task_id = await queue.enqueue(
        tweet_ids,
        force_refresh=False,
        source="batch_api",
        priority=SummarizationPriority.HIGH,
    )

    logger.info(f"创建摘要补缺任务: {task_id} - {len(tweet_ids)} 条推文")

    return SummaryBackfillResponse(
        task_id=task_id, status="pending", tweet_count=len(tweet_ids)
    )


@router.get(
    "/reset/preview",
    response_model=SummaryPreviewResponse,
)
async def preview_reset(
    since: datetime = Query(..., description="起始时间（含），ISO 8601 格式"),
    until: datetime = Query(..., description="截止时间（不含），ISO 8601 格式"),
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryPreviewResponse:
    """预览摘要重置：查询时间范围内的推文数量。"""
    if since >= until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="until 必须晚于 since",
        )
    count = await get_summarization_read_repo(session).count_tweets_in_window(
        since, until
    )
    return SummaryPreviewResponse(tweet_count=count)


@router.post(
    "/reset",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SummaryResetResponse,
    responses={
        404: {"model": ErrorResponse, "description": "指定时间范围内没有推文"},
        422: {"model": ErrorResponse, "description": "无效的时间范围"},
    },
)
async def start_reset(
    request: SummaryResetRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryResetResponse:
    """启动摘要重置任务：强制重新生成时间范围内所有推文的摘要。

    通过集中式摘要队列异步处理，支持优先级和背压。
    """
    tweet_ids = await get_summarization_read_repo(session).list_tweet_ids_in_window(
        request.since, request.until
    )

    if not tweet_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定时间范围内没有推文",
        )

    from src.summarization.services.summarization_queue import (
        SummarizationPriority,
        SummarizationQueue,
    )

    queue = SummarizationQueue.get_instance()
    task_id = await queue.enqueue(
        tweet_ids,
        force_refresh=True,
        source="batch_api",
        priority=SummarizationPriority.HIGH,
    )

    logger.info(f"创建摘要重置任务: {task_id} - {len(tweet_ids)} 条推文")

    return SummaryResetResponse(
        task_id=task_id, status="pending", tweet_count=len(tweet_ids)
    )
