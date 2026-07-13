"""Admin API 路由。

提供管理端点，包括手动触发抓取任务和查询任务状态。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from src.mcp.security import audit_log
from src.scraper import ScrapingService, TaskRegistry, TaskStatus
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 全局服务实例（延迟初始化）
_scraping_service: ScrapingService | None = None
_task_registry: TaskRegistry | None = None


def get_scraping_service() -> ScrapingService:
    """获取抓取服务实例。"""
    global _scraping_service
    if _scraping_service is None:
        _scraping_service = ScrapingService()
    return _scraping_service


def get_task_registry() -> TaskRegistry:
    """获取任务注册表实例。"""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry.get_instance()
    return _task_registry


class ScrapeRequest:
    """抓取请求模型。

    Attributes:
        usernames: 逗号分隔的用户名字符串
        limit: 每个用户抓取的推文数量限制
    """

    def __init__(
        self,
        usernames: str,
        limit: int = 100,
    ):
        """初始化抓取请求。

        Args:
            usernames: 逗号分隔的用户名字符串
            limit: 每个用户抓取的推文数量限制

        Raises:
            ValueError: 如果参数无效
        """
        if not usernames or not usernames.strip():
            raise ValueError("usernames 不能为空")

        # 解析用户名列表
        parsed_usernames = [u.strip() for u in usernames.split(",") if u.strip()]

        if not parsed_usernames:
            raise ValueError("至少需要提供一个有效的用户名")

        # 验证 limit 范围
        if not (1 <= limit <= 1000):
            raise ValueError("limit 必须在 1-1000 之间")

        # 验证用户名格式（Twitter 用户名规则：1-15 字符，字母数字下划线）
        for username in parsed_usernames:
            if not (1 <= len(username) <= 15):
                raise ValueError(f"用户名 '{username}' 长度必须在 1-15 字符之间")
            if not username.replace("_", "").isalnum():
                raise ValueError(f"用户名 '{username}' 只能包含字母、数字和下划线")

        self.usernames = usernames
        self.parsed_usernames = parsed_usernames
        self.limit = limit


class ScrapeResponse:
    """抓取响应模型。

    Attributes:
        task_id: 任务 ID
        status: 任务状态
    """

    def __init__(self, task_id: str, task_status: str):
        """初始化抓取响应。

        Args:
            task_id: 任务 ID
            task_status: 任务状态
        """
        self.task_id = task_id
        self.status = task_status

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "task_id": self.task_id,
            "status": self.status,
        }


class TaskStatusResponse:
    """任务状态响应模型。

    Attributes:
        task_id: 任务 ID
        status: 任务状态
        result: 任务结果（完成时）
        error: 错误信息（失败时）
        created_at: 创建时间
        started_at: 开始时间
        completed_at: 完成时间
        progress: 进度信息
        metadata: 元数据
    """

    def __init__(
        self,
        task_id: str,
        task_status: Literal["pending", "running", "completed", "failed"],
        task_name: str = "",
        result: dict[str, Any] | None = None,
        error: str | None = None,
        created_at: datetime | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        progress: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """初始化任务状态响应。

        Args:
            task_id: 任务 ID
            task_status: 任务状态
            task_name: 任务名称
            result: 任务结果（完成时）
            error: 错误信息（失败时）
            created_at: 创建时间
            started_at: 开始时间
            completed_at: 完成时间
            progress: 进度信息
            metadata: 元数据
        """
        self.task_id = task_id
        self.task_name = task_name
        self.status = task_status
        self.result = result
        self.error = error
        self.created_at = created_at
        self.started_at = started_at
        self.completed_at = completed_at
        self.progress = progress or {"current": 0, "total": 0, "percentage": 0.0}
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "metadata": self.metadata,
        }


async def _run_scraping_task_async(task_id: str, usernames: list[str], limit: int) -> None:
    """在主事件循环中异步运行抓取任务。

    使用 asyncio.create_task 在主事件循环中执行，避免创建新的事件循环导致
    跨循环问题（摘要队列入队、数据库 session、Semaphore 等均绑定到主循环）。

    Args:
        task_id: 任务 ID
        usernames: 用户名列表
        limit: 抓取限制
    """
    import time

    from src.logging_config import trace_id_var

    # 设置 trace_id，使所有下游日志（去重、摘要）可追踪
    trace_id_var.set(task_id)

    service = get_scraping_service()
    registry = get_task_registry()

    # 读取 DB 中的 manual_limit 配置（与 scheduled_job.py 一致）
    from src.scraper.scheduled_job import get_active_follows_async

    follows_data = await get_active_follows_async()
    manual_limits = {
        f["username"]: f["manual_limit"]
        for f in follows_data
        if f["manual_limit"] and f["username"] in usernames
    }
    if manual_limits:
        logger.info(f"Admin 抓取任务使用 manual_limits: {manual_limits}")

    start_time = time.time()
    logger.info(
        f"抓取任务开始: {len(usernames)} 个用户, limit={limit}",
        extra={"task_id": task_id, "event": "scrape_task_start"},
    )

    try:
        await service.scrape_users(
            usernames=usernames,
            limit=limit,
            task_id=task_id,
            manual_limits=manual_limits or None,
        )
        elapsed = time.time() - start_time
        logger.info(
            f"抓取任务完成: 耗时 {elapsed:.1f}s",
            extra={
                "task_id": task_id,
                "event": "scrape_task_done",
                "processing_time_ms": int(elapsed * 1000),
            },
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.exception(
            f"后台抓取任务执行失败: {e}",
            extra={
                "task_id": task_id,
                "event": "scrape_task_failed",
                "error_type": type(e).__name__,
            },
        )
        registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))


async def _run_backfill_all_async(task_id: str, max_tweets: int) -> None:
    """后台执行批量 Article 回溯。

    逐账号顺序调用 backfill_articles_for_user，避免 API rate limit。
    通过 TaskRegistry 更新进度和最终结果。

    Args:
        task_id: 任务 ID
        max_tweets: 每个账号扫描的推文数量上限
    """
    import time

    from src.scraper.scheduled_job import get_active_follows_async

    service = get_scraping_service()
    registry = get_task_registry()

    start_time = time.time()
    logger.info(
        f"Article 批量回溯开始: max_tweets={max_tweets}",
        extra={"task_id": task_id, "event": "backfill_all_start"},
    )

    try:
        follows = await get_active_follows_async()
        total = len(follows)
        details: list[dict[str, Any]] = []
        summary = {"total_checked": 0, "total_found": 0, "total_skipped": 0, "total_errors": 0}

        for i, follow in enumerate(follows):
            username = follow["username"]
            registry.update_progress(task_id, i, total)

            try:
                result = await service.backfill_articles_for_user(
                    username,
                    max_tweets=max_tweets,
                )
            except Exception as e:
                logger.warning(f"Article 批量回溯跳过 {username}: {e}")
                result = {"checked": 0, "found": 0, "skipped": 0, "errors": 1}

            details.append(
                {
                    "username": username,
                    "checked": result.get("checked", 0),
                    "found": result.get("found", 0),
                    "skipped": result.get("skipped", 0),
                    "errors": result.get("errors", 0),
                }
            )
            summary["total_checked"] += result.get("checked", 0)
            summary["total_found"] += result.get("found", 0)
            summary["total_skipped"] += result.get("skipped", 0)
            summary["total_errors"] += result.get("errors", 0)

        registry.update_progress(task_id, total, total)
        elapsed = time.time() - start_time
        logger.info(
            f"Article 批量回溯完成: {total} 个账号, found={summary['total_found']}, "
            f"耗时 {elapsed:.1f}s",
            extra={"task_id": task_id, "event": "backfill_all_done"},
        )
        registry.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={"total_users": total, "summary": summary, "details": details},
        )
    except Exception as e:
        logger.exception(
            f"Article 批量回溯失败: {e}",
            extra={"task_id": task_id, "event": "backfill_all_failed"},
        )
        registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))


@router.post("/scrape", status_code=status.HTTP_202_ACCEPTED)
async def start_scraping(
    request: dict[str, Any],
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """启动手动抓取任务。

    接收用户名列表和抓取限制，创建异步抓取任务并立即返回任务 ID。

    Args:
        request: 请求体，包含 usernames 和 limit
        background_tasks: FastAPI 后台任务管理器

    Returns:
        dict: 包含 task_id 和 status 的响应

    Raises:
        HTTPException: 400 无效输入，409 任务冲突
    """
    try:
        # 解析请求
        usernames = request.get("usernames", "")
        limit = request.get("limit", 100)

        # 兼容 list 和 str 两种格式
        if isinstance(usernames, list):
            usernames = ",".join(str(u).strip() for u in usernames if str(u).strip())

        scrape_request = ScrapeRequest(usernames=usernames, limit=limit)
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    registry = get_task_registry()
    registry.cleanup_expired_tasks(ttl_hours=24)

    # 检查是否有相同的任务正在运行
    for task in registry.get_all_tasks():
        if (
            task["status"] == TaskStatus.RUNNING
            and task.get("metadata", {}).get("usernames") == scrape_request.usernames
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"相同的抓取任务正在执行中: {task['task_id']}",
            )

    # 创建任务
    task_id = registry.create_task(
        task_name=f"抓取 {len(scrape_request.parsed_usernames)} 个用户",
        metadata={
            "usernames": scrape_request.usernames,
            "limit": scrape_request.limit,
        },
    )

    # 在主事件循环中创建异步任务（避免跨循环问题）
    asyncio.create_task(
        _run_scraping_task_async(
            task_id,
            scrape_request.parsed_usernames,
            scrape_request.limit,
        ),
        name=f"scrape-{task_id}",
    )

    logger.info(f"创建抓取任务: {task_id} - {scrape_request.parsed_usernames}")

    audit_log(
        "start_scraping",
        "scrape",
        params={"usernames": scrape_request.parsed_usernames, "limit": scrape_request.limit},
        source="api",
        user=_admin.name,
    )

    return ScrapeResponse(
        task_id=task_id,
        task_status="pending",
    ).to_dict()


@router.get("/scrape/{task_id}")
async def get_scraping_status(
    task_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """查询抓取任务状态。

    返回任务的当前状态、进度和结果（如果已完成）。

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

    response = TaskStatusResponse(
        task_id=task_data["task_id"],
        task_status=task_data["status"],
        task_name=task_data.get("task_name", ""),
        result=task_data.get("result"),
        error=task_data.get("error"),
        created_at=task_data.get("created_at"),
        started_at=task_data.get("started_at"),
        completed_at=task_data.get("completed_at"),
        progress=task_data.get("progress"),
        metadata=task_data.get("metadata"),
    )

    return response.to_dict()


@router.get("/scrape")
async def list_scraping_tasks(
    status: Literal["pending", "running", "completed", "failed"] | None = None,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> list[dict[str, Any]]:
    """列出所有抓取任务。

    Args:
        status: 可选的状态过滤器

    Returns:
        list[dict]: 任务列表
    """
    registry = get_task_registry()

    if status is None:
        tasks = registry.get_all_tasks()
    else:
        task_status = TaskStatus(status)
        tasks = registry.get_tasks_by_status(task_status)

    return [
        TaskStatusResponse(
            task_id=t["task_id"],
            task_status=t["status"],
            task_name=t.get("task_name", ""),
            result=t.get("result"),
            error=t.get("error"),
            created_at=t.get("created_at"),
            started_at=t.get("started_at"),
            completed_at=t.get("completed_at"),
            progress=t.get("progress"),
            metadata=t.get("metadata"),
        ).to_dict()
        for t in tasks
    ]


@router.delete("/scrape/{task_id}")
async def delete_scraping_task(
    task_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """删除抓取任务。

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
        logger.info(f"删除任务: {task_id}")

        audit_log(
            "delete_scraping_task",
            "delete",
            params={"task_id": task_id},
            source="api",
            user=_admin.name,
        )

        return {"message": f"任务 {task_id} 已删除"}

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="删除任务失败",
    )


@router.post("/articles/backfill", response_model=None)
async def backfill_articles(
    request: dict[str, Any],
    _admin: UserDomain = Depends(get_current_admin_user),
) -> JSONResponse | dict[str, Any]:
    """回溯 X Articles。

    支持两种模式：
    1. 单用户模式：{"username": "xxx", "max_tweets": 200} → 同步返回 200
    2. 批量模式：{"all": true, "max_tweets": 200} → 异步后台任务，返回 202 + task_id
       通过 GET /api/admin/scrape/{task_id} 查询进度和结果。

    注意：每次 API 调用消耗 100 credits，请合理设置 max_tweets。
    """
    backfill_all = request.get("all", False)
    max_tweets = request.get("max_tweets", 200)

    if not isinstance(max_tweets, int) or not (1 <= max_tweets <= 1000):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_tweets 必须在 1-1000 之间",
        )

    service = get_scraping_service()

    # ── 批量模式：后台任务 + 立即返回 task_id ──
    if backfill_all:
        registry = get_task_registry()
        task_id = registry.create_task(
            task_name="Article 批量回溯",
            metadata={"mode": "backfill_all", "max_tweets": max_tweets},
        )

        asyncio.create_task(
            _run_backfill_all_async(task_id, max_tweets),
            name=f"backfill-all-{task_id}",
        )

        logger.info(f"创建 Article 批量回溯任务: {task_id}")

        audit_log(
            "backfill_articles",
            "backfill_all",
            params={"max_tweets": max_tweets},
            source="api",
            user=_admin.name,
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"task_id": task_id, "status": "pending"},
        )

    # ── 单用户模式 ──
    username = request.get("username", "").strip()

    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username 不能为空",
        )

    if not (1 <= len(username) <= 15):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"用户名 '{username}' 长度必须在 1-15 字符之间",
        )

    if not username.replace("_", "").isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"用户名 '{username}' 只能包含字母、数字和下划线",
        )

    try:
        result = await service.backfill_articles_for_user(
            username,
            max_tweets=max_tweets,
        )
    except Exception as e:
        logger.exception(f"Article 回溯异常: username={username}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Article 回溯失败: {e}",
        )

    logger.info(f"Article 回溯完成: username={username}, result={result}")

    audit_log(
        "backfill_articles",
        "backfill",
        params={"username": username, "max_tweets": max_tweets},
        source="api",
        user=_admin.name,
    )

    return {
        "username": username,
        "result": result,
    }
