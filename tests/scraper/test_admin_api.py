"""Admin API 端点测试。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.scraper import TaskRegistry, TaskStatus


@pytest.fixture
def client(test_settings):  # noqa: ARG001 - 参数确保设置已加载
    """创建测试客户端。"""
    # Mock 后台任务以防止实际执行
    with patch("src.api.routes.admin.BackgroundTasks.add_task"):
        yield TestClient(app)


@pytest.fixture
def clean_registry():
    """清理任务注册表。"""
    registry = TaskRegistry.get_instance()
    registry.clear_all()
    yield
    registry.clear_all()


class TestScrapeRequest:
    """测试 ScrapeRequest 模型。"""

    def test_valid_request(self):
        """测试有效的请求。"""
        from src.api.routes.admin import ScrapeRequest

        request = ScrapeRequest(usernames="user1,user2", limit=100)

        assert request.usernames == "user1,user2"
        assert request.parsed_usernames == ["user1", "user2"]
        assert request.limit == 100

    def test_valid_request_single_user(self):
        """测试单个用户的请求。"""
        from src.api.routes.admin import ScrapeRequest

        request = ScrapeRequest(usernames="single_user", limit=50)

        assert request.parsed_usernames == ["single_user"]
        assert request.limit == 50

    def test_valid_request_with_spaces(self):
        """测试带空格的用户名。"""
        from src.api.routes.admin import ScrapeRequest

        request = ScrapeRequest(usernames=" user1 , user2 , user3 ", limit=100)

        assert request.parsed_usernames == ["user1", "user2", "user3"]

    def test_empty_usernames_raises_error(self):
        """测试空用户名抛出错误。"""
        from src.api.routes.admin import ScrapeRequest

        with pytest.raises(ValueError, match="usernames 不能为空"):
            ScrapeRequest(usernames="", limit=100)

        with pytest.raises(ValueError, match="usernames 不能为空"):
            ScrapeRequest(usernames="   ", limit=100)

    def test_only_commas_raises_error(self):
        """测试只有逗号抛出错误。"""
        from src.api.routes.admin import ScrapeRequest

        with pytest.raises(ValueError, match="至少需要提供一个有效的用户名"):
            ScrapeRequest(usernames=",,,", limit=100)

    def test_limit_below_minimum(self):
        """测试 limit 小于最小值。"""
        from src.api.routes.admin import ScrapeRequest

        with pytest.raises(ValueError, match="limit 必须在 1-1000 之间"):
            ScrapeRequest(usernames="user1", limit=0)

        with pytest.raises(ValueError, match="limit 必须在 1-1000 之间"):
            ScrapeRequest(usernames="user1", limit=-1)

    def test_limit_above_maximum(self):
        """测试 limit 大于最大值。"""
        from src.api.routes.admin import ScrapeRequest

        with pytest.raises(ValueError, match="limit 必须在 1-1000 之间"):
            ScrapeRequest(usernames="user1", limit=1001)

    def test_invalid_username_too_long(self):
        """测试用户名太长。"""
        from src.api.routes.admin import ScrapeRequest

        long_username = "a" * 16
        with pytest.raises(ValueError, match="长度必须在 1-15 字符之间"):
            ScrapeRequest(usernames=long_username, limit=100)

    def test_invalid_username_special_chars(self):
        """测试用户名包含特殊字符。"""
        from src.api.routes.admin import ScrapeRequest

        with pytest.raises(ValueError, match="只能包含字母、数字和下划线"):
            ScrapeRequest(usernames="user@name", limit=100)

        with pytest.raises(ValueError, match="只能包含字母、数字和下划线"):
            ScrapeRequest(usernames="user-name", limit=100)


class TestScrapeResponse:
    """测试 ScrapeResponse 模型。"""

    def test_to_dict(self):
        """测试转换为字典。"""
        from src.api.routes.admin import ScrapeResponse

        response = ScrapeResponse(task_id="test-id", task_status="pending")

        assert response.to_dict() == {
            "task_id": "test-id",
            "status": "pending",
        }


class TestTaskStatusResponse:
    """测试 TaskStatusResponse 模型。"""

    def test_to_dict(self):
        """测试转换为字典。"""
        from src.api.routes.admin import TaskStatusResponse

        now = datetime.now()
        response = TaskStatusResponse(
            task_id="test-id",
            task_status="completed",
            result={"new_tweets": 10},
            created_at=now,
            started_at=now,
            completed_at=now,
            progress={"current": 10, "total": 10, "percentage": 100.0},
        )

        result = response.to_dict()

        assert result["task_id"] == "test-id"
        assert result["status"] == "completed"
        assert result["result"] == {"new_tweets": 10}
        assert result["created_at"] == now.isoformat()
        assert result["progress"]["percentage"] == 100.0


class TestStartScrapingEndpoint:
    """测试 POST /api/admin/scrape 端点。"""

    def test_start_scraping_success(self, client, clean_registry):
        """测试成功启动抓取任务。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user1,user2", "limit": 100},
        )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        # 验证任务已创建
        registry = TaskRegistry.get_instance()
        task = registry.get_task_status(data["task_id"])
        assert task is not None
        assert task["status"] == TaskStatus.PENDING

    def test_start_scraping_default_limit(self, client, clean_registry):
        """测试使用默认 limit。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user1"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data

    def test_start_scraping_empty_usernames(self, client, clean_registry):
        """测试空用户名返回 400 错误。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "", "limit": 100},
        )

        assert response.status_code == 400
        assert "不能为空" in response.json()["detail"]

    def test_start_scraping_invalid_limit(self, client, clean_registry):
        """测试无效 limit 返回 400 错误。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user1", "limit": 2000},
        )

        assert response.status_code == 400
        assert "limit" in response.json()["detail"]

    def test_start_scraping_invalid_username(self, client, clean_registry):
        """测试无效用户名返回 400 错误。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user@invalid", "limit": 100},
        )

        assert response.status_code == 400
        assert "用户名" in response.json()["detail"]

    def test_start_scraping_duplicate_task(self, client, clean_registry):
        """测试重复任务返回 409 错误。"""
        # 创建第一个任务
        registry = TaskRegistry.get_instance()
        task_id = registry.create_task(
            task_name="测试任务",
            metadata={"usernames": "user1,user2", "limit": 100},
        )
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        # 尝试创建相同任务
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user1,user2", "limit": 100},
        )

        assert response.status_code == 409
        assert "正在执行中" in response.json()["detail"]


class TestGetScrapingStatusEndpoint:
    """测试 GET /api/admin/scrape/{task_id} 端点。"""

    def test_get_task_status_success(self, client, clean_registry):
        """测试成功获取任务状态。"""
        registry = TaskRegistry.get_instance()
        task_id = registry.create_task(
            task_name="测试任务",
            metadata={"usernames": "user1"},
        )
        registry.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={"new_tweets": 10},
        )

        response = client.get(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task_id
        assert data["status"] == "completed"
        assert data["result"]["new_tweets"] == 10

    def test_get_task_status_not_found(self, client, clean_registry):
        """测试任务不存在返回 404。"""
        response = client.get("/api/admin/scrape/nonexistent-id")

        assert response.status_code == 404
        assert "不存在" in response.json()["detail"]

    def test_get_task_status_with_error(self, client, clean_registry):
        """测试获取失败任务的状态。"""
        registry = TaskRegistry.get_instance()
        task_id = registry.create_task(task_name="失败任务")
        registry.update_task_status(
            task_id,
            TaskStatus.FAILED,
            error="API 错误",
        )

        response = client.get(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"] == "API 错误"


class TestListScrapingTasksEndpoint:
    """测试 GET /api/admin/scrape 端点。"""

    def test_list_all_tasks(self, client, clean_registry):
        """测试列出所有任务。"""
        registry = TaskRegistry.get_instance()
        task_id_1 = registry.create_task(task_name="任务 1")
        task_id_2 = registry.create_task(task_name="任务 2")
        registry.update_task_status(task_id_1, TaskStatus.COMPLETED)
        registry.update_task_status(task_id_2, TaskStatus.RUNNING)

        response = client.get("/api/admin/scrape")

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 2
        task_ids = {t["task_id"] for t in tasks}
        assert task_id_1 in task_ids
        assert task_id_2 in task_ids

    def test_list_tasks_by_status(self, client, clean_registry):
        """测试按状态过滤任务。"""
        registry = TaskRegistry.get_instance()
        task_id_1 = registry.create_task(task_name="已完成任务")
        task_id_2 = registry.create_task(task_name="运行中任务")
        registry.update_task_status(task_id_1, TaskStatus.COMPLETED)
        registry.update_task_status(task_id_2, TaskStatus.RUNNING)

        response = client.get("/api/admin/scrape?status=completed")

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == task_id_1
        assert tasks[0]["status"] == "completed"

    def test_list_empty_tasks(self, client, clean_registry):
        """测试列出空任务列表。"""
        response = client.get("/api/admin/scrape")

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 0


class TestDeleteScrapingTaskEndpoint:
    """测试 DELETE /api/admin/scrape/{task_id} 端点。"""

    def test_delete_completed_task(self, client, clean_registry):
        """测试删除已完成的任务。"""
        registry = TaskRegistry.get_instance()
        task_id = registry.create_task(task_name="已完成任务")
        registry.update_task_status(task_id, TaskStatus.COMPLETED)

        response = client.delete(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 200
        assert "已删除" in response.json()["message"]

        # 验证任务已删除
        assert registry.get_task_status(task_id) is None

    def test_delete_running_task_fails(self, client, clean_registry):
        """测试删除运行中的任务失败。"""
        registry = TaskRegistry.get_instance()
        task_id = registry.create_task(task_name="运行中任务")
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        response = client.delete(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 409
        assert "不能删除" in response.json()["detail"]

    def test_delete_nonexistent_task(self, client, clean_registry):
        """测试删除不存在的任务。"""
        response = client.delete("/api/admin/scrape/nonexistent-id")

        assert response.status_code == 404
        assert "不存在" in response.json()["detail"]

    def test_delete_failed_task(self, client, clean_registry):
        """测试删除失败的任务。"""
        registry = TaskRegistry.get_instance()
        task_id = registry.create_task(task_name="失败任务")
        registry.update_task_status(
            task_id,
            TaskStatus.FAILED,
            error="错误信息",
        )

        response = client.delete(f"/api/admin/scrape/{task_id}")

        assert response.status_code == 200
