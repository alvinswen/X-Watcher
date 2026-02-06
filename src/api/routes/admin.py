"""Admin API 路由。

提供管理端点，包括手动触发抓取任务和查询任务状态。
"""

import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.scraper import ScrapingService, TaskRegistry, TaskStatus

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
        parsed_usernames = [
            u.strip()
            for u in usernames.split(",")
            if u.strip()
        ]

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

    def to_dict(self) -> dict:
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
        result: dict | None = None,
        error: str | None = None,
        created_at: datetime | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        progress: dict | None = None,
        metadata: dict | None = None,
    ):
        """初始化任务状态响应。

        Args:
            task_id: 任务 ID
            task_status: 任务状态
            result: 任务结果（完成时）
            error: 错误信息（失败时）
            created_at: 创建时间
            started_at: 开始时间
            completed_at: 完成时间
            progress: 进度信息
            metadata: 元数据
        """
        self.task_id = task_id
        self.status = task_status
        self.result = result
        self.error = error
        self.created_at = created_at
        self.started_at = started_at
        self.completed_at = completed_at
        self.progress = progress or {"current": 0, "total": 0, "percentage": 0.0}
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "metadata": self.metadata,
        }


def _run_scraping_task(task_id: str, usernames: list[str], limit: int) -> None:
    """在后台运行抓取任务。

    Args:
        task_id: 任务 ID
        usernames: 用户名列表
        limit: 抓取限制
    """
    service = get_scraping_service()
    registry = get_task_registry()
    loop = None

    async def _execute() -> None:
        try:
            await service.scrape_users(
                usernames=usernames,
                limit=limit,
                task_id=task_id,
            )
        except Exception as e:
            logger.exception(f"后台抓取任务执行失败: {e}")
            registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))

    try:
        # 在新的事件循环中运行异步任务
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_execute())
    except Exception as e:
        logger.exception(f"后台任务执行异常: {e}")
        registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
    finally:
        if loop:
            loop.close()


@router.post("/scrape", status_code=status.HTTP_202_ACCEPTED)
async def start_scraping(
    request: dict,
    background_tasks: BackgroundTasks,
) -> dict:
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

        scrape_request = ScrapeRequest(usernames=usernames, limit=limit)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    registry = get_task_registry()

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

    # 添加后台任务
    background_tasks.add_task(
        _run_scraping_task,
        task_id,
        scrape_request.parsed_usernames,
        scrape_request.limit,
    )

    logger.info(f"创建抓取任务: {task_id} - {scrape_request.parsed_usernames}")

    return ScrapeResponse(
        task_id=task_id,
        task_status="pending",
    ).to_dict()


@router.get("/scrape/{task_id}")
async def get_scraping_status(task_id: str) -> dict:
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
) -> list[dict]:
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
async def delete_scraping_task(task_id: str) -> dict:
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
        return {"message": f"任务 {task_id} 已删除"}

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="删除任务失败",
    )
