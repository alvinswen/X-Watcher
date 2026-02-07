"""任务注册表。

管理异步抓取任务的状态和生命周期。
"""

import logging
import threading
import uuid
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


def _update_task_metrics(status: TaskStatus, old_status: TaskStatus | None = None) -> None:
    """更新 Prometheus 任务指标。

    Args:
        status: 当前任务状态
        old_status: 之前的状态（用于转换跟踪）
    """
    try:
        from src.config import get_settings

        settings = get_settings()
        if not settings.prometheus_enabled:
            return

        from src.monitoring import metrics

        # 更新任务状态计数器
        metrics.tasks_total.labels(status=status.value).inc()

        # 更新活跃任务数
        registry = TaskRegistry.get_instance()
        active_count = len(registry.get_tasks_by_status(TaskStatus.RUNNING))
        metrics.active_tasks.set(active_count)

    except Exception:
        # 静默失败，避免指标更新影响业务逻辑
        pass


class TaskStatus(str, Enum):
    """任务状态枚举。

    表示任务在生命周期中的不同状态。
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRegistry:
    """任务注册表单例。

    管理异步任务的状态、进度和结果。
    使用线程锁确保并发安全。
    """

    _instance: "TaskRegistry | None" = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls) -> "TaskRegistry":
        """实现单例模式。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化任务注册表。"""
        if not TaskRegistry._initialized:
            self._tasks: dict[str, dict] = {}
            self._task_lock = threading.RLock()
            TaskRegistry._initialized = True
            logger.debug("TaskRegistry 单例已初始化")

    @classmethod
    def get_instance(cls) -> "TaskRegistry":
        """获取 TaskRegistry 单例实例。

        Returns:
            TaskRegistry: 单例实例
        """
        return cls()

    def create_task(
        self,
        task_name: str,
        metadata: dict | None = None,
    ) -> str:
        """创建一个新任务。

        Args:
            task_name: 任务名称/描述
            metadata: 可选的元数据字典

        Returns:
            str: 唯一的任务 ID (UUID)
        """
        task_id = str(uuid.uuid4())

        task_data = {
            "task_id": task_id,
            "task_name": task_name,
            "status": TaskStatus.PENDING,
            "created_at": datetime.now(),
            "started_at": None,
            "completed_at": None,
            "progress": {
                "current": 0,
                "total": 0,
                "percentage": 0.0,
            },
            "result": None,
            "error": None,
            "metadata": metadata or {},
        }

        with self._task_lock:
            self._tasks[task_id] = task_data

        # 更新 Prometheus 指标
        _update_task_metrics(TaskStatus.PENDING)

        logger.info(f"创建任务: {task_name} (ID: {task_id})")
        return task_id

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        """更新任务状态。

        Args:
            task_id: 任务 ID
            status: 新状态
            result: 可选的结果数据（完成时）
            error: 可选的错误信息（失败时）
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(f"尝试更新不存在的任务: {task_id}")
                return

            old_status = task["status"]
            task["status"] = status

            now = datetime.now()

            if status == TaskStatus.RUNNING and old_status == TaskStatus.PENDING:
                task["started_at"] = now
                logger.info(f"任务开始执行: {task_id}")

            elif status == TaskStatus.COMPLETED:
                task["completed_at"] = now
                if result is not None:
                    task["result"] = result
                logger.info(f"任务完成: {task_id}")

            elif status == TaskStatus.FAILED:
                task["completed_at"] = now
                if error is not None:
                    task["error"] = error
                logger.error(f"任务失败: {task_id} - {error}")

            # 更新 Prometheus 指标
            _update_task_metrics(status, old_status)

    def update_progress(
        self,
        task_id: str,
        current: int,
        total: int,
    ) -> None:
        """更新任务进度。

        Args:
            task_id: 任务 ID
            current: 当前进度值
            total: 总量
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is None:
                return

            percentage = (current / total * 100) if total > 0 else 0.0
            task["progress"] = {
                "current": current,
                "total": total,
                "percentage": round(percentage, 2),
            }

    def get_task_status(self, task_id: str) -> dict | None:
        """获取任务状态。

        Args:
            task_id: 任务 ID

        Returns:
            dict | None: 任务状态字典，如果任务不存在返回 None
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None

            # 返回副本以避免外部修改
            return self._copy_task_data(task)

    def get_all_tasks(self) -> list[dict]:
        """获取所有任务。

        Returns:
            list[dict]: 所有任务的列表
        """
        with self._task_lock:
            return [self._copy_task_data(task) for task in self._tasks.values()]

    def get_tasks_by_status(self, status: TaskStatus) -> list[dict]:
        """获取指定状态的所有任务。

        Args:
            status: 任务状态

        Returns:
            list[dict]: 符合条件的任务列表
        """
        with self._task_lock:
            return [
                self._copy_task_data(task)
                for task in self._tasks.values()
                if task["status"] == status
            ]

    def is_task_running(self, task_id: str) -> bool:
        """检查任务是否正在运行。

        Args:
            task_id: 任务 ID

        Returns:
            bool: 如果任务正在运行返回 True
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            return task is not None and task["status"] == TaskStatus.RUNNING

    def delete_task(self, task_id: str) -> bool:
        """删除任务。

        Args:
            task_id: 任务 ID

        Returns:
            bool: 如果删除成功返回 True
        """
        with self._task_lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                logger.debug(f"删除任务: {task_id}")
                return True
            return False

    def cleanup_expired_tasks(self, ttl_hours: int = 24) -> int:
        """清理过期任务。

        删除已完成或失败且超过 TTL 的任务。
        运行中的任务不会被删除。

        Args:
            ttl_hours: 生存时间（小时）

        Returns:
            int: 清理的任务数量
        """
        now = datetime.now()
        expired_ids = []

        with self._task_lock:
            for task_id, task in self._tasks.items():
                # 只清理已完成或失败的任务
                if task["status"] not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    continue

                completed_at = task.get("completed_at")
                if completed_at is None:
                    continue

                # 检查是否过期
                if now - completed_at > timedelta(hours=ttl_hours):
                    expired_ids.append(task_id)

            # 删除过期任务
            for task_id in expired_ids:
                del self._tasks[task_id]

        if expired_ids:
            logger.info(f"清理了 {len(expired_ids)} 个过期任务")

        return len(expired_ids)

    def get_task_count(self) -> int:
        """获取任务总数。

        Returns:
            int: 当前任务数量
        """
        with self._task_lock:
            return len(self._tasks)

    def clear_all(self) -> None:
        """清空所有任务。"""
        with self._task_lock:
            self._tasks.clear()
        logger.info("清空所有任务")

    def _copy_task_data(self, task: dict) -> dict:
        """创建任务数据的副本。

        Args:
            task: 原始任务数据

        Returns:
            dict: 任务数据副本
        """
        # 深拷贝以避免外部修改
        return {
            "task_id": task["task_id"],
            "task_name": task["task_name"],
            "status": task["status"],
            "created_at": task["created_at"],
            "started_at": task["started_at"],
            "completed_at": task["completed_at"],
            "progress": task["progress"].copy(),
            "result": task["result"],
            "error": task["error"],
            "metadata": task["metadata"].copy(),
        }
