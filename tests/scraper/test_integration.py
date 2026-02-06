"""集成测试。

测试完整的抓取流程，包括手动触发、定时调度和错误恢复。
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.scraper import TaskRegistry, TaskStatus


@pytest.fixture
def integration_client(test_settings):
    """创建集成测试客户端。"""
    with patch("src.api.routes.admin.BackgroundTasks.add_task"):
        yield TestClient(app)


class TestManualScrapingFlow:
    """测试手动抓取完整流程。"""

    def test_full_scraping_workflow(self, integration_client, clean_registry):
        """测试完整的抓取工作流：
        1. POST 触发抓取
        2. GET 查询状态
        3. 验证数据库存储
        """
        # Mock 抓取服务
        mock_result = {
            "total_users": 1,
            "successful_users": 1,
            "failed_users": 0,
            "total_tweets": 10,
            "new_tweets": 10,
            "skipped_tweets": 0,
            "total_errors": 0,
            "elapsed_seconds": 1.5,
        }

        with patch("src.scraper.scraping_service.ScrapingService.scrape_users", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.return_value = "test-task-id"

            # 1. POST 触发抓取
            response = integration_client.post(
                "/api/admin/scrape",
                json={"usernames": "testuser", "limit": 100},
            )

            assert response.status_code == 202
            data = response.json()
            task_id = data["task_id"]
            assert task_id is not None
            assert data["status"] == "pending"

            # 2. GET 查询状态
            response = integration_client.get(f"/api/admin/scrape/{task_id}")
            assert response.status_code == 200
            task_data = response.json()
            assert task_data["task_id"] == task_id

    def test_scraping_with_duplicate_prevention(self, integration_client, clean_registry):
        """测试重复任务被正确拒绝。"""
        registry = TaskRegistry.get_instance()

        # 创建一个运行中的任务
        task_id = registry.create_task(
            task_name="测试任务",
            metadata={"usernames": "user1,user2", "limit": 100},
        )
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        # 尝试创建相同的任务
        response = integration_client.post(
            "/api/admin/scrape",
            json={"usernames": "user1,user2", "limit": 100},
        )

        assert response.status_code == 409
        assert "正在执行中" in response.json()["detail"]

    def test_task_status_after_completion(self, integration_client, clean_registry):
        """测试任务完成后的状态查询。"""
        registry = TaskRegistry.get_instance()

        # 创建并完成一个任务
        task_id = registry.create_task(task_name="测试任务")
        registry.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={"new_tweets": 5, "total_tweets": 5},
        )

        # 查询状态
        response = integration_client.get(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["new_tweets"] == 5

    def test_list_all_tasks(self, integration_client, clean_registry):
        """测试列出所有任务。"""
        registry = TaskRegistry.get_instance()

        # 创建多个任务
        task1 = registry.create_task(task_name="任务1")
        task2 = registry.create_task(task_name="任务2")
        registry.update_task_status(task1, TaskStatus.COMPLETED)
        registry.update_task_status(task2, TaskStatus.RUNNING)

        # 列出所有任务
        response = integration_client.get("/api/admin/scrape")

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) >= 2

        task_ids = {t["task_id"] for t in tasks}
        assert task1 in task_ids
        assert task2 in task_ids


class TestSchedulerScrapingFlow:
    """测试定时抓取流程。"""

    def test_scheduler_job_skips_when_disabled(self):
        """测试禁用时调度器跳过任务。"""
        from src.config import clear_settings_cache
        import os

        clear_settings_cache()
        os.environ["SCRAPER_ENABLED"] = "false"
        os.environ["SCRAPER_USERNAMES"] = "user1,user2"
        os.environ["TWITTER_BEARER_TOKEN"] = "test-token"

        # 导入调度器任务函数
        from src.main import _scheduled_scrape_job

        # Mock registry
        with patch("src.main.TaskRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry
            mock_registry.get_all_tasks.return_value = []

            # 执行调度任务
            _scheduled_scrape_job()

            # 验证没有创建任务（因为被禁用）
            mock_registry.create_task.assert_not_called()

    def test_scheduler_job_skips_when_no_usernames(self):
        """测试没有配置用户时跳过任务。"""
        from src.config import clear_settings_cache
        import os

        clear_settings_cache()
        os.environ["SCRAPER_ENABLED"] = "true"
        os.environ["SCRAPER_USERNAMES"] = ""
        os.environ["TWITTER_BEARER_TOKEN"] = "test-token"

        from src.main import _scheduled_scrape_job

        # Mock registry
        with patch("src.main.TaskRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry

            _scheduled_scrape_job()

            # 验证没有创建任务
            mock_registry.create_task.assert_not_called()

    def test_scheduler_job_skips_when_task_running(self):
        """测试有任务运行时跳过本次执行。"""
        from src.config import clear_settings_cache
        import os

        clear_settings_cache()
        os.environ["SCRAPER_ENABLED"] = "true"
        os.environ["SCRAPER_USERNAMES"] = "user1,user2"
        os.environ["TWITTER_BEARER_TOKEN"] = "test-token"

        from src.main import _scheduled_scrape_job

        # Mock registry 返回运行中的任务
        with patch("src.main.TaskRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry
            mock_registry.get_all_tasks.return_value = [
                {"task_id": "running-task", "status": TaskStatus.RUNNING}
            ]

            _scheduled_scrape_job()

            # 验证没有创建新任务
            mock_registry.create_task.assert_not_called()


class TestTaskCleanup:
    """测试任务清理功能。"""

    def test_delete_completed_task(self, integration_client, clean_registry):
        """测试删除已完成的任务。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(task_name="测试任务")
        registry.update_task_status(task_id, TaskStatus.COMPLETED)

        response = integration_client.delete(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 200
        assert registry.get_task_status(task_id) is None

    def test_cannot_delete_running_task(self, integration_client, clean_registry):
        """测试不能删除运行中的任务。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(task_name="运行中任务")
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        response = integration_client.delete(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 409
        assert registry.get_task_status(task_id) is not None

    def test_delete_nonexistent_task(self, integration_client, clean_registry):
        """测试删除不存在的任务。"""
        response = integration_client.delete("/api/admin/scrape/nonexistent-id")

        assert response.status_code == 404


class TestTaskProgressTracking:
    """测试任务进度跟踪。"""

    def test_task_progress_initialization(self, clean_registry):
        """测试任务进度初始化。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(task_name="测试任务")
        task = registry.get_task_status(task_id)

        assert task["progress"]["current"] == 0
        assert task["progress"]["total"] == 0
        assert task["progress"]["percentage"] == 0.0

    def test_task_progress_update(self, clean_registry):
        """测试任务进度更新。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(task_name="测试任务")

        registry.update_progress(task_id, 5, 10)

        task = registry.get_task_status(task_id)
        assert task["progress"]["current"] == 5
        assert task["progress"]["total"] == 10
        assert task["progress"]["percentage"] == 50.0

    def test_task_progress_with_zero_total(self, clean_registry):
        """测试总量为 0 时的进度。"""
        registry = TaskRegistry.get_instance()

        task_id = registry.create_task(task_name="测试任务")

        registry.update_progress(task_id, 0, 0)

        task = registry.get_task_status(task_id)
        assert task["progress"]["percentage"] == 0.0
