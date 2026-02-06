"""TaskRegistry 单元测试。

测试异步任务状态管理功能。
"""

import time
from datetime import datetime, timedelta
from enum import Enum

import pytest

from src.scraper.task_registry import TaskRegistry, TaskStatus


class MockTask:
    """Mock 任务对象。"""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.executed = False


class TestTaskRegistry:
    """TaskRegistry 测试类。"""

    def setup_method(self):
        """每个测试方法前执行：重置单例。"""
        TaskRegistry._instance = None
        TaskRegistry._initialized = False

    def test_singleton_pattern(self):
        """测试单例模式。"""
        registry1 = TaskRegistry.get_instance()
        registry2 = TaskRegistry.get_instance()

        assert registry1 is registry2

    def test_create_task(self):
        """测试创建任务。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")

        assert task_id is not None
        assert isinstance(task_id, str)
        assert len(task_id) == 36  # UUID 格式

        # 验证任务已注册
        status = registry.get_task_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.PENDING
        assert "created_at" in status

    def test_create_task_with_metadata(self):
        """测试创建带元数据的任务。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(
            "test_task",
            metadata={"usernames": "user1,user2", "limit": 100}
        )

        status = registry.get_task_status(task_id)
        assert status["metadata"]["usernames"] == "user1,user2"
        assert status["metadata"]["limit"] == 100

    def test_create_multiple_tasks(self):
        """测试创建多个任务。"""
        registry = TaskRegistry.get_instance()

        task_id1 = registry.create_task("task1")
        task_id2 = registry.create_task("task2")

        assert task_id1 != task_id2

        # 验证两个任务都存在
        assert registry.get_task_status(task_id1) is not None
        assert registry.get_task_status(task_id2) is not None

    def test_update_task_status_to_running(self):
        """测试更新任务状态为运行中。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        status = registry.get_task_status(task_id)
        assert status["status"] == TaskStatus.RUNNING
        assert status["started_at"] is not None

    def test_update_task_status_to_completed(self):
        """测试更新任务状态为已完成。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")
        registry.update_task_status(task_id, TaskStatus.RUNNING)
        registry.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={"success_count": 10, "skipped_count": 2}
        )

        status = registry.get_task_status(task_id)
        assert status["status"] == TaskStatus.COMPLETED
        assert status["completed_at"] is not None
        assert status["result"]["success_count"] == 10

    def test_update_task_status_to_failed(self):
        """测试更新任务状态为失败。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")
        error_msg = "API 认证失败"
        registry.update_task_status(
            task_id,
            TaskStatus.FAILED,
            error=error_msg
        )

        status = registry.get_task_status(task_id)
        assert status["status"] == TaskStatus.FAILED
        assert status["error"] == error_msg
        assert status["completed_at"] is not None

    def test_update_nonexistent_task(self):
        """测试更新不存在的任务（应静默忽略）。"""
        registry = TaskRegistry.get_instance()

        # 不应抛出异常
        registry.update_task_status("nonexistent_id", TaskStatus.RUNNING)

    def test_get_task_status(self):
        """测试获取任务状态。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")
        status = registry.get_task_status(task_id)

        assert status is not None
        assert "task_id" in status
        assert "task_name" in status
        assert "status" in status
        assert "created_at" in status
        assert status["task_name"] == "test_task"

    def test_get_nonexistent_task_status(self):
        """测试获取不存在的任务状态。"""
        registry = TaskRegistry.get_instance()

        status = registry.get_task_status("nonexistent_id")
        assert status is None

    def test_is_task_running(self):
        """测试检查任务是否正在运行。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")

        # 初始状态不是运行中
        assert not registry.is_task_running(task_id)

        # 更新为运行中
        registry.update_task_status(task_id, TaskStatus.RUNNING)
        assert registry.is_task_running(task_id)

        # 完成
        registry.update_task_status(task_id, TaskStatus.COMPLETED)
        assert not registry.is_task_running(task_id)

    def test_is_task_running_nonexistent(self):
        """测试检查不存在的任务是否运行中。"""
        registry = TaskRegistry.get_instance()

        assert not registry.is_task_running("nonexistent_id")

    def test_get_all_tasks(self):
        """测试获取所有任务。"""
        registry = TaskRegistry.get_instance()

        task_id1 = registry.create_task("task1")
        task_id2 = registry.create_task("task2")

        all_tasks = registry.get_all_tasks()

        assert len(all_tasks) == 2
        task_ids = [t["task_id"] for t in all_tasks]
        assert task_id1 in task_ids
        assert task_id2 in task_ids

    def test_get_tasks_by_status(self):
        """测试按状态筛选任务。"""
        registry = TaskRegistry.get_instance()

        task_id1 = registry.create_task("task1")
        task_id2 = registry.create_task("task2")
        task_id3 = registry.create_task("task3")

        registry.update_task_status(task_id1, TaskStatus.RUNNING)
        registry.update_task_status(task_id2, TaskStatus.COMPLETED)

        running_tasks = registry.get_tasks_by_status(TaskStatus.RUNNING)
        completed_tasks = registry.get_tasks_by_status(TaskStatus.COMPLETED)

        assert len(running_tasks) == 1
        assert len(completed_tasks) == 1
        assert running_tasks[0]["task_id"] == task_id1
        assert completed_tasks[0]["task_id"] == task_id2

    def test_delete_task(self):
        """测试删除任务。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")
        assert registry.get_task_status(task_id) is not None

        registry.delete_task(task_id)
        assert registry.get_task_status(task_id) is None

    def test_cleanup_expired_tasks(self):
        """测试清理过期任务。"""
        registry = TaskRegistry.get_instance()

        # 创建一个任务并设置为很久前完成
        task_id = registry.create_task("old_task")
        registry.update_task_status(task_id, TaskStatus.COMPLETED)

        # 手动修改完成时间为 25 小时前
        old_time = datetime.now() - timedelta(hours=25)
        registry._tasks[task_id]["completed_at"] = old_time

        # 创建一个新任务
        new_task_id = registry.create_task("new_task")

        # 清理过期任务
        cleaned_count = registry.cleanup_expired_tasks(ttl_hours=24)

        assert cleaned_count == 1
        assert registry.get_task_status(task_id) is None
        assert registry.get_task_status(new_task_id) is not None

    def test_cleanup_does_not_delete_running_tasks(self):
        """测试清理不删除运行中的任务。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        # 手动修改开始时间为 25 小时前
        old_time = datetime.now() - timedelta(hours=25)
        registry._tasks[task_id]["started_at"] = old_time

        # 清理过期任务
        cleaned_count = registry.cleanup_expired_tasks(ttl_hours=24)

        # 运行中的任务不应被清理
        assert cleaned_count == 0
        assert registry.get_task_status(task_id) is not None

    def test_task_status_enum(self):
        """测试任务状态枚举。"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"

    def test_concurrent_task_creation(self):
        """测试并发创建任务（线程安全）。"""
        import threading

        registry = TaskRegistry.get_instance()
        task_ids = []
        errors = []

        def create_task(name: str):
            try:
                task_id = registry.create_task(name)
                task_ids.append(task_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=create_task, args=(f"task_{i}",))
            for i in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(task_ids) == 10
        assert len(set(task_ids)) == 10  # 所有 ID 唯一

    def test_get_task_count(self):
        """测试获取任务计数。"""
        registry = TaskRegistry.get_instance()

        assert registry.get_task_count() == 0

        registry.create_task("task1")
        registry.create_task("task2")
        registry.create_task("task3")

        assert registry.get_task_count() == 3

    def test_clear_all_tasks(self):
        """测试清空所有任务。"""
        registry = TaskRegistry.get_instance()

        registry.create_task("task1")
        registry.create_task("task2")

        assert registry.get_task_count() == 2

        registry.clear_all()

        assert registry.get_task_count() == 0

    def test_task_progress_tracking(self):
        """测试任务进度跟踪。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task("test_task")

        # 更新进度
        registry.update_progress(task_id, current=5, total=10)

        status = registry.get_task_status(task_id)
        assert status["progress"]["current"] == 5
        assert status["progress"]["total"] == 10
        assert status["progress"]["percentage"] == 50.0
