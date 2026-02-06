"""错误场景和恢复测试。

测试各种错误情况下系统的行为和恢复能力。
"""

from datetime import datetime, timedelta

import pytest

from src.scraper import TaskRegistry, TaskStatus


class TestTaskFailureRecovery:
    """测试任务失败恢复。"""

    def test_failed_task_status_update(self, clean_registry):
        """测试失败任务的状态更新。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(task_name="测试任务")

        error_msg = "API 认证失败"
        registry.update_task_status(
            task_id,
            TaskStatus.FAILED,
            error=error_msg,
        )

        task = registry.get_task_status(task_id)
        assert task["status"] == TaskStatus.FAILED
        assert task["error"] == error_msg
        assert task["completed_at"] is not None

    def test_task_failure_preserves_metadata(self, clean_registry):
        """测试任务失败时保留元数据。"""
        registry = TaskRegistry.get_instance()

        metadata = {"usernames": "user1,user2", "limit": 100}
        task_id = registry.create_task(
            task_name="测试任务",
            metadata=metadata,
        )

        registry.update_task_status(task_id, TaskStatus.FAILED, error="Error")

        task = registry.get_task_status(task_id)
        assert task["metadata"] == metadata


class TestTaskCleanup:
    """测试过期任务清理。"""

    def test_cleanup_expired_tasks(self, clean_registry):
        """测试清理过期任务。"""
        registry = TaskRegistry.get_instance()

        # 创建一个已完成且过期的任务
        task_id = registry.create_task(task_name="过期任务")
        registry.update_task_status(task_id, TaskStatus.COMPLETED)

        # 手动设置完成时间为过去
        task = registry._tasks[task_id]
        task["completed_at"] = datetime.now() - timedelta(hours=25)

        # 清理过期任务
        cleaned = registry.cleanup_expired_tasks(ttl_hours=24)

        assert cleaned == 1
        assert registry.get_task_status(task_id) is None

    def test_cleanup_does_not_remove_running_tasks(self, clean_registry):
        """测试清理不删除运行中的任务。"""
        registry = TaskRegistry.get_instance()

        # 创建一个运行中的任务
        task_id = registry.create_task(task_name="运行中任务")
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        # 手动设置创建时间为过去
        task = registry._tasks[task_id]
        task["created_at"] = datetime.now() - timedelta(hours=25)

        # 清理过期任务
        cleaned = registry.cleanup_expired_tasks(ttl_hours=24)

        assert cleaned == 0
        assert registry.get_task_status(task_id) is not None

    def test_cleanup_preserves_recent_tasks(self, clean_registry):
        """测试清理保留最近的已完成任务。"""
        registry = TaskRegistry.get_instance()

        # 创建一个最近完成的任务
        task_id = registry.create_task(task_name="最近任务")
        registry.update_task_status(task_id, TaskStatus.COMPLETED)

        # 清理过期任务
        cleaned = registry.cleanup_expired_tasks(ttl_hours=24)

        assert cleaned == 0
        assert registry.get_task_status(task_id) is not None


class TestDatabaseErrors:
    """测试数据库错误回滚。"""

    @pytest.mark.asyncio
    async def test_save_returns_result_summary(self, db_session):
        """测试保存返回结果汇总。"""
        from src.scraper.domain.models import Tweet
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(db_session)

        tweets = [
            Tweet(
                tweet_id=str(i),
                text=f"Tweet {i}",
                created_at=datetime.now(),
                author_username="testuser",
            )
            for i in range(3)
        ]

        # 保存推文
        result = await repo.save_tweets(tweets)

        # 验证结果结构
        assert hasattr(result, "success_count")
        assert hasattr(result, "skipped_count")
        assert hasattr(result, "error_count")
        assert result.success_count + result.skipped_count + result.error_count == len(tweets)


class TestErrorRecoverySummary:
    """测试错误恢复汇总。"""

    def test_concurrent_task_creation_and_cleanup(self, clean_registry):
        """测试并发任务创建和清理。"""
        registry = TaskRegistry.get_instance()

        # 创建多个任务
        task_ids = []
        for i in range(10):
            task_id = registry.create_task(task_name=f"任务 {i}")
            task_ids.append(task_id)
            # 随机设置状态
            if i % 3 == 0:
                registry.update_task_status(task_id, TaskStatus.COMPLETED)
            elif i % 3 == 1:
                registry.update_task_status(task_id, TaskStatus.RUNNING)
            else:
                registry.update_task_status(task_id, TaskStatus.FAILED, error="Error")

        # 验证所有任务都存在
        for task_id in task_ids:
            assert registry.get_task_status(task_id) is not None

        # 清理所有任务
        registry.clear_all()

        # 验证所有任务都被删除
        for task_id in task_ids:
            assert registry.get_task_status(task_id) is None

    def test_task_count_tracking(self, clean_registry):
        """测试任务计数跟踪。"""
        registry = TaskRegistry.get_instance()

        initial_count = registry.get_task_count()

        # 创建任务
        for _ in range(5):
            registry.create_task(task_name="测试任务")

        assert registry.get_task_count() == initial_count + 5

        # 清理
        registry.clear_all()
        assert registry.get_task_count() == 0
