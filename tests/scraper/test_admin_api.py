"""Admin API 端点测试。"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.scraper import TaskRegistry, TaskStatus
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN


@pytest.fixture(autouse=True)
def override_auth():
    """覆盖管理员认证依赖，避免 401。"""
    app.dependency_overrides[get_current_admin_user] = lambda: BOOTSTRAP_ADMIN
    yield
    app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.fixture
def client(test_settings):  # noqa: ARG001 - 参数确保设置已加载
    """创建测试客户端。"""
    # Mock asyncio.create_task 以防止实际执行后台抓取任务
    with patch("src.api.routes.admin.asyncio.create_task"):
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

        response = ScrapeResponse(task_id="test-id", status="pending")

        assert response.model_dump() == {
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
            status="completed",
            result={"new_tweets": 10},
            created_at=now,
            started_at=now,
            completed_at=now,
            progress={"current": 10, "total": 10, "percentage": 100.0},
        )

        result = response.model_dump(mode="json")

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
        """测试空用户名返回 422 结构化错误。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "", "limit": 100},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body"]
        assert detail["type"] == "value_error"

    def test_start_scraping_invalid_limit(self, client, clean_registry):
        """测试无效 limit 返回 422 结构化错误。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user1", "limit": 2000},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body", "limit"]
        assert detail["type"] == "value_error"

    def test_start_scraping_invalid_username(self, client, clean_registry):
        """测试无效用户名返回 422 结构化错误。"""
        response = client.post(
            "/api/admin/scrape",
            json={"usernames": "user@invalid", "limit": 100},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body"]
        assert detail["type"] == "value_error"

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


class TestRunScrapingTaskAsync:
    """CHG-031 的 REST 后台任务本体验证。"""

    @pytest.mark.asyncio
    async def test_tc_build_383_rest_helper_delegates_without_manual_limits(self):
        """TC-BUILD-383: REST 辅助函数不再传入内联 manual_limits。"""
        from src.api.routes.admin import _run_scraping_task_async

        service = Mock()
        service.scrape_users = AsyncMock(return_value="task-383")
        with (
            patch(
                "src.api.routes.admin.get_scraping_service", return_value=service
            ),
            patch("src.api.routes.admin.get_task_registry", return_value=Mock()),
        ):
            await _run_scraping_task_async("task-383", ["alice"], 100)

        service.scrape_users.assert_awaited_once_with(
            usernames=["alice"],
            limit=100,
            task_id="task-383",
        )

    @pytest.mark.asyncio
    async def test_tc_build_399_rest_path_queries_manual_limits_exactly_once(self):
        """TC-BUILD-399: REST 依赖服务层单点解析，仓储查询精确一次。"""
        from src.api.routes.admin import _run_scraping_task_async
        from src.scraper.scraping_service import ScrapingService

        service = ScrapingService(
            client=AsyncMock(),
            parser=Mock(),
            validator=Mock(),
            repository=AsyncMock(),
        )
        service._scrape_with_semaphore = AsyncMock(
            return_value={
                "username": "alice",
                "success": True,
                "fetched": 0,
                "new": 0,
                "skipped": 0,
                "errors": 0,
                "error_message": None,
            }
        )
        service._profile_service.sync_user_profiles = AsyncMock()
        resolver = AsyncMock(return_value={})

        with (
            patch(
                "src.api.routes.admin.get_scraping_service", return_value=service
            ),
            patch("src.api.routes.admin.get_task_registry", return_value=Mock()),
            patch(
                "src.scraper.scheduled_job.resolve_manual_limits", new=resolver
            ),
        ):
            await _run_scraping_task_async("task-399", ["alice"], 100)

        resolver.assert_awaited_once_with(["alice"])


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


@pytest.mark.asyncio
class TestBackfillArticlesEndpoint:
    """测试 POST /api/admin/articles/backfill 端点。

    使用 async_client (httpx.AsyncClient) 避免 TestClient lifespan 挂起问题。
    """

    @pytest.fixture
    def mock_service(self):
        """Mock ScrapingService。"""
        service = AsyncMock()
        service.backfill_articles_for_user = AsyncMock()
        return service

    async def test_backfill_articles_success(self, async_client, mock_service):
        """测试成功回溯 Articles。"""
        mock_service.backfill_articles_for_user.return_value = {
            "checked": 50,
            "found": 3,
            "skipped": 45,
            "errors": 2,
        }

        with patch(
            "src.api.routes.admin.get_article_fetch_service",
            return_value=mock_service,
        ):
            response = await async_client.post(
                "/api/admin/articles/backfill",
                json={"username": "testuser", "max_tweets": 100},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["result"]["checked"] == 50
        assert data["result"]["found"] == 3
        assert data["result"]["skipped"] == 45
        assert data["result"]["errors"] == 2
        mock_service.backfill_articles_for_user.assert_called_once_with(
            "testuser",
            max_tweets=100,
        )

    async def test_backfill_articles_default_max_tweets(self, async_client, mock_service):
        """测试使用默认 max_tweets。"""
        mock_service.backfill_articles_for_user.return_value = {
            "checked": 0,
            "found": 0,
            "skipped": 0,
            "errors": 0,
        }

        with patch(
            "src.api.routes.admin.get_article_fetch_service",
            return_value=mock_service,
        ):
            response = await async_client.post(
                "/api/admin/articles/backfill",
                json={"username": "testuser"},
            )

        assert response.status_code == 200
        mock_service.backfill_articles_for_user.assert_called_once_with(
            "testuser",
            max_tweets=200,
        )

    async def test_backfill_articles_empty_username(self, async_client):
        """测试空用户名返回 422 结构化错误。"""
        response = await async_client.post(
            "/api/admin/articles/backfill",
            json={"username": ""},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body"]
        assert detail["type"] == "value_error"

    async def test_backfill_articles_invalid_username(self, async_client):
        """测试无效用户名返回 422 结构化错误。"""
        response = await async_client.post(
            "/api/admin/articles/backfill",
            json={"username": "user@invalid"},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body"]
        assert detail["type"] == "value_error"

    async def test_backfill_articles_username_too_long(self, async_client):
        """测试用户名过长返回 422 结构化错误。"""
        response = await async_client.post(
            "/api/admin/articles/backfill",
            json={"username": "a" * 16},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body"]
        assert detail["type"] == "value_error"

    async def test_backfill_articles_invalid_max_tweets(self, async_client):
        """测试无效 max_tweets 返回 422 结构化错误。"""
        response = await async_client.post(
            "/api/admin/articles/backfill",
            json={"username": "testuser", "max_tweets": 2000},
        )

        assert response.status_code == 422
        detail = response.json()["detail"][0]
        assert detail["loc"] == ["body", "max_tweets"]
        assert detail["type"] == "less_than_equal"

    async def test_backfill_articles_service_error(self, async_client, mock_service):
        """测试服务异常返回 500。"""
        mock_service.backfill_articles_for_user.side_effect = RuntimeError("DB 连接失败")

        with patch(
            "src.api.routes.admin.get_article_fetch_service",
            return_value=mock_service,
        ):
            response = await async_client.post(
                "/api/admin/articles/backfill",
                json={"username": "testuser"},
            )

        assert response.status_code == 500
        assert "回溯失败" in response.json()["detail"]

    async def test_backfill_all_accounts_returns_202(self, async_client, mock_service):
        """测试批量模式立即返回 202 + task_id（后台执行）。"""
        with patch("src.api.routes.admin.asyncio.create_task"):
            response = await async_client.post(
                "/api/admin/articles/backfill",
                json={"all": True, "max_tweets": 100},
            )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"

    async def test_backfill_all_accounts_empty_follows_returns_202(
        self, async_client, mock_service
    ):
        """测试无活跃关注时也返回 202（后台任务会处理空列表）。"""
        with patch("src.api.routes.admin.asyncio.create_task"):
            response = await async_client.post(
                "/api/admin/articles/backfill",
                json={"all": True},
            )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"


@pytest.mark.asyncio
class TestCHG032RestLifecycle:
    """CHG-032 TC-BUILD-401/402/403/408/409/410/420/425/430/432。"""

    async def test_tc_build_401_scrape_task_closes_service_once(self):
        from src.api.routes.admin import _run_scraping_task_async

        service = Mock()
        service.scrape_users = AsyncMock(return_value="task-401")
        service.close = AsyncMock()
        with (
            patch("src.api.routes.admin.get_scraping_service", return_value=service),
            patch("src.api.routes.admin.get_task_registry", return_value=Mock()),
        ):
            await _run_scraping_task_async("task-401", ["alice"], 100)

        service.close.assert_awaited_once_with()

    async def test_tc_build_402_backfill_batch_closes_once(self):
        from src.api.routes.admin import _run_backfill_all_async

        service = Mock()
        service.backfill_articles_for_user = AsyncMock(
            return_value={"checked": 1, "found": 1, "skipped": 0, "errors": 0}
        )
        service.close = AsyncMock()
        registry = Mock()
        with (
            patch("src.api.routes.admin.get_article_fetch_service", return_value=service),
            patch("src.api.routes.admin.get_task_registry", return_value=registry),
            patch(
                "src.scraper.scheduled_job.get_active_follows_async",
                new=AsyncMock(return_value=[{"username": "alice"}, {"username": "bob"}]),
            ),
        ):
            await _run_backfill_all_async("task-402", 20)

        assert service.backfill_articles_for_user.await_count == 2
        service.close.assert_awaited_once_with()

    async def test_tc_build_403_single_backfill_constructs_and_closes(self):
        from src.api.routes.admin import BackfillRequest, backfill_articles

        service = Mock()
        service.backfill_articles_for_user = AsyncMock(return_value={"checked": 1})
        service.close = AsyncMock()
        with (
            patch("src.api.routes.admin.get_article_fetch_service", return_value=service) as factory,
            patch("src.api.routes.admin.audit_log"),
        ):
            result = await backfill_articles(
                BackfillRequest(username="alice", max_tweets=20),
                BOOTSTRAP_ADMIN,
            )

        assert result.model_dump() == {
            "username": "alice",
            "result": {"checked": 1},
        }
        factory.assert_called_once_with()
        service.close.assert_awaited_once_with()

    async def test_tc_build_408_close_failure_is_fail_soft(self, caplog):
        from src.api.routes.admin import _close_scraping_service

        service = Mock()
        service.close = AsyncMock(side_effect=RuntimeError("close failed"))
        with caplog.at_level("WARNING"):
            await _close_scraping_service(service, " (task_id=task-408)")

        assert "close failed" in caplog.text

    async def test_tc_build_409_scraping_factory_is_stateless(self):
        from src.api.routes.admin import get_scraping_service

        assert get_scraping_service() is not get_scraping_service()

    async def test_tc_build_410_task_registry_remains_singleton(self):
        from src.api.routes.admin import get_task_registry

        assert get_task_registry() is get_task_registry()

    async def test_tc_build_420_rest_close_warning_contains_task_ids(self, caplog):
        from src.api.routes.admin import _close_scraping_service

        with caplog.at_level("WARNING"):
            for task_id in ("task-401", "task-402"):
                service = Mock()
                service.close = AsyncMock(side_effect=RuntimeError("boom"))
                await _close_scraping_service(service, f" (task_id={task_id})")

        assert "task_id=task-401" in caplog.text
        assert "task_id=task-402" in caplog.text

    async def test_tc_build_425_batch_endpoint_does_not_construct_service(self):
        from src.api.routes.admin import BackfillRequest, backfill_articles

        registry = Mock()
        registry.create_task.return_value = "task-425"

        def close_background_coro(coro, *, name):
            coro.close()
            return Mock(name=name)

        with (
            patch("src.api.routes.admin.get_article_fetch_service") as factory,
            patch("src.api.routes.admin.get_task_registry", return_value=registry),
            patch("src.api.routes.admin.asyncio.create_task", side_effect=close_background_coro),
            patch("src.api.routes.admin.audit_log"),
        ):
            response = await backfill_articles(
                BackfillRequest(all=True, max_tweets=20),
                BOOTSTRAP_ADMIN,
            )

        assert response.status_code == 202
        factory.assert_not_called()

    async def test_tc_build_430_unconfigured_mock_close_stays_compatible(self):
        from src.api.routes.admin import _run_scraping_task_async

        service = Mock()
        service.scrape_users = AsyncMock(return_value="task-430")
        with (
            patch("src.api.routes.admin.get_scraping_service", return_value=service),
            patch("src.api.routes.admin.get_task_registry", return_value=Mock()),
        ):
            await _run_scraping_task_async("task-430", ["alice"], 100)

        service.scrape_users.assert_awaited_once()

    async def test_tc_build_432_registry_wrapper_delegates_every_time(self):
        from src.api.routes.admin import get_task_registry

        registry = Mock()
        with patch("src.api.routes.admin.TaskRegistry.get_instance", return_value=registry) as getter:
            assert get_task_registry() is registry
            assert get_task_registry() is registry

        assert getter.call_count == 2
