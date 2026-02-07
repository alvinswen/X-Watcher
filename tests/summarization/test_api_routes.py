"""摘要 API 端点集成测试。

测试摘要相关的 FastAPI 端点。
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import clear_settings_cache
from src.main import app
from src.scraper import TaskRegistry
from src.summarization.domain.models import (
    CostStats,
    SummaryRecord,
)
from src.summarization.infrastructure.models import SummaryOrm


@pytest.fixture(autouse=True)
def reset_task_registry():
    """在每个测试前重置任务注册表。"""
    registry = TaskRegistry.get_instance()
    registry.clear_all()
    yield
    registry.clear_all()


@pytest.fixture(autouse=True)
def setup_test_env():
    """设置测试环境变量。"""
    # 设置 LLM API 密钥
    os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"

    yield

    # 清理环境变量
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("MINIMAX_API_KEY", None)
    clear_settings_cache()


@pytest.fixture
def mock_summarization_service():
    """模拟摘要服务。"""
    service = MagicMock()

    # 模拟 summarize_tweets 方法
    service.summarize_tweets = AsyncMock()

    # 模拟 regenerate_summary 方法
    service.regenerate_summary = AsyncMock()

    return service


@pytest.fixture
def sample_summary_record():
    """示例摘要记录。"""
    return SummaryRecord(
        summary_id="test-summary-id",
        tweet_id="test-tweet-id",
        summary_text="这是一条测试摘要，包含了足够的字符以满足最小长度要求。该摘要描述了一条关于人工智能技术发展的重要推文内容。",
        translation_text="This is a test summary with enough characters to meet the minimum length requirement.",
        model_provider="openrouter",
        model_name="claude-sonnet-4.5",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        cached=False,
        content_hash="abc123",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestBatchSummaryEndpoint:
    """测试批量摘要端点。"""

    def test_post_batch_creates_task(self, client: TestClient):
        """测试 POST /batch 创建任务，返回 task_id。"""
        # 清除任务注册表
        registry = TaskRegistry.get_instance()
        registry.clear_all()

        response = client.post(
            "/api/summaries/batch",
            json={
                "tweet_ids": ["tweet1", "tweet2", "tweet3"],
                "force_refresh": False,
            },
        )

        # 验证 API 立即返回 202 和 task_id
        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        # 验证任务已注册（后台任务可能已经开始执行，所以只验证非 None）
        task = registry.get_task_status(data["task_id"])
        assert task is not None
        assert "task_id" in task

    def test_post_batch_with_force_refresh(self, client: TestClient):
        """测试 POST /batch 支持 force_refresh 参数。"""
        response = client.post(
            "/api/summaries/batch",
            json={
                "tweet_ids": ["tweet1"],
                "force_refresh": True,
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data

        # 验证元数据包含 force_refresh
        registry = TaskRegistry.get_instance()
        task = registry.get_task_status(data["task_id"])
        assert task["metadata"]["force_refresh"] is True

    def test_post_batch_empty_tweet_ids_raises_error(self, client: TestClient):
        """测试空 tweet_ids 列表返回 400 错误。"""
        response = client.post(
            "/api/summaries/batch",
            json={
                "tweet_ids": [],
                "force_refresh": False,
            },
        )

        assert response.status_code == 422  # Pydantic 验证错误

    def test_post_batch_max_tweet_ids(self, client: TestClient):
        """测试 tweet_ids 超过最大数量返回 422 错误。"""
        response = client.post(
            "/api/summaries/batch",
            json={
                "tweet_ids": [f"tweet{i}" for i in range(1001)],  # 超过 1000
                "force_refresh": False,
            },
        )

        assert response.status_code == 422  # Pydantic 验证错误


class TestGetTweetSummaryEndpoint:
    """测试查询单条推文摘要端点。"""

    def test_get_existing_summary_returns_data(
        self,
        client: TestClient,
        async_session,
        sample_summary_record,
    ):
        """测试 GET /tweets/{id} 存在返回摘要。"""
        # 创建摘要记录
        orm_record = SummaryOrm.from_domain(sample_summary_record)
        async_session.add(orm_record)
        # 注意：此处在同步上下文中调用异步 commit，会触发警告但不影响功能
        # 更好的方式是在 fixture 中预先创建数据
        import asyncio
        asyncio.run(async_session.commit())

        # 模拟 get_async_session_maker 返回测试会话
        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: async_session,
        ):
            response = client.get(f"/api/summaries/tweets/{sample_summary_record.tweet_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["summary_id"] == sample_summary_record.summary_id
        assert data["tweet_id"] == sample_summary_record.tweet_id
        assert data["summary_text"] == sample_summary_record.summary_text
        assert data["model_provider"] == sample_summary_record.model_provider

    def test_get_nonexistent_summary_returns_404(self, client: TestClient):
        """测试 GET /tweets/{id} 不存在返回 404。"""
        # 模拟一个返回 None 的仓储
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_summary_by_tweet = AsyncMock(return_value=None)

        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: mock_session,
        ):
            with patch(
                "src.summarization.api.routes.SummarizationRepository",
                return_value=mock_repo,
            ):
                response = client.get("/api/summaries/tweets/nonexistent-tweet")

        assert response.status_code == 404


class TestGetCostStatsEndpoint:
    """测试成本统计端点。"""

    def test_get_stats_without_date_filter(
        self,
        client: TestClient,
    ):
        """测试 GET /stats 不带日期过滤。"""
        # 模拟统计数据
        mock_stats = CostStats(
            start_date=None,
            end_date=None,
            total_cost_usd=0.01,
            total_tokens=1500,
            prompt_tokens=1000,
            completion_tokens=500,
            provider_breakdown={
                "openrouter": {"total_tokens": 1000, "cost_usd": 0.005, "count": 5}
            },
        )

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_cost_stats = AsyncMock(return_value=mock_stats)

        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: mock_session,
        ):
            with patch(
                "src.summarization.api.routes.SummarizationRepository",
                return_value=mock_repo,
            ):
                response = client.get("/api/summaries/stats")

        assert response.status_code == 200
        data = response.json()
        assert "total_cost_usd" in data
        assert "total_tokens" in data
        assert "provider_breakdown" in data

    def test_get_stats_with_date_range(
        self,
        client: TestClient,
    ):
        """测试 GET /stats 带日期范围筛选。"""
        start_date = "2024-01-01T00:00:00Z"
        end_date = "2024-12-31T23:59:59Z"

        # 模拟仓储返回统计数据
        mock_stats = CostStats(
            start_date=datetime.fromisoformat(start_date.replace("Z", "+00:00")),
            end_date=datetime.fromisoformat(end_date.replace("Z", "+00:00")),
            total_cost_usd=0.01,
            total_tokens=1500,
            prompt_tokens=1000,
            completion_tokens=500,
            provider_breakdown={
                "openrouter": {"total_tokens": 1000, "cost_usd": 0.005, "count": 5}
            },
        )

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_cost_stats = AsyncMock(return_value=mock_stats)

        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: mock_session,
        ):
            with patch(
                "src.summarization.api.routes.SummarizationRepository",
                return_value=mock_repo,
            ):
                response = client.get(
                    f"/api/summaries/stats?start_date={start_date}&end_date={end_date}"
                )

        assert response.status_code == 200
        data = response.json()
        assert data["total_cost_usd"] == 0.01
        assert data["total_tokens"] == 1500

    def test_get_stats_invalid_date_range_returns_400(self, client: TestClient):
        """测试无效日期范围返回 400。"""
        response = client.get(
            "/api/summaries/stats?start_date=2024-12-31&end_date=2024-01-01"
        )

        assert response.status_code == 400


class TestRegenerateSummaryEndpoint:
    """测试重新生成摘要端点。"""

    def test_post_regenerate_with_valid_tweet(
        self,
        client: TestClient,
        sample_summary_record,
    ):
        """测试 POST /regenerate 强制刷新缓存。"""
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_service = MagicMock()

        # 模拟服务返回新摘要
        mock_service.regenerate_summary = AsyncMock(
            return_value=MagicMock(unwrap=lambda: sample_summary_record)
        )

        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: mock_session,
        ):
            with patch(
                "src.summarization.api.routes.SummarizationRepository",
                return_value=mock_repo,
            ):
                with patch(
                    "src.summarization.api.routes.create_summarization_service",
                    return_value=mock_service,
                ):
                    response = client.post(f"/api/summaries/tweets/{sample_summary_record.tweet_id}/regenerate")

        assert response.status_code == 200
        data = response.json()
        assert data["summary_id"] == sample_summary_record.summary_id

    def test_post_regenerate_nonexistent_tweet_returns_500(self, client: TestClient):
        """测试 POST /regenerate 不存在的推文返回错误。"""
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_service = MagicMock()

        # 模拟服务返回失败
        from returns.result import Failure

        mock_service.regenerate_summary = AsyncMock(
            return_value=Failure(ValueError("推文未找到"))
        )

        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: mock_session,
        ):
            with patch(
                "src.summarization.api.routes.SummarizationRepository",
                return_value=mock_repo,
            ):
                with patch(
                    "src.summarization.api.routes.create_summarization_service",
                    return_value=mock_service,
                ):
                    response = client.post("/api/summaries/tweets/nonexistent/regenerate")

        assert response.status_code == 500


class TestTaskStatusEndpoints:
    """测试任务状态端点。"""

    def test_get_task_status_returns_task_data(self, client: TestClient):
        """测试 GET /tasks/{task_id} 返回任务状态。"""
        registry = TaskRegistry.get_instance()

        # 创建测试任务
        task_id = registry.create_task(
            task_name="测试摘要任务",
            metadata={"tweet_count": 10},
        )

        # 更新为完成状态
        from src.scraper import TaskStatus
        registry.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={"total_tweets": 10, "total_groups": 5},
        )

        response = client.get(f"/api/summaries/tasks/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task_id
        assert data["status"] == "completed"
        assert data["result"]["total_tweets"] == 10

    def test_get_nonexistent_task_returns_404(self, client: TestClient):
        """测试 GET /tasks/{task_id} 不存在的任务返回 404。"""
        response = client.get("/api/summaries/tasks/nonexistent-task-id")

        assert response.status_code == 404

    def test_delete_completed_task(self, client: TestClient):
        """测试 DELETE /tasks/{task_id} 删除已完成任务。"""
        registry = TaskRegistry.get_instance()

        # 创建并完成任务
        task_id = registry.create_task(task_name="测试任务")
        from src.scraper import TaskStatus
        registry.update_task_status(task_id, TaskStatus.COMPLETED)

        response = client.delete(f"/api/summaries/tasks/{task_id}")

        assert response.status_code == 200
        assert "已删除" in response.json()["message"]

        # 验证任务已删除
        assert registry.get_task_status(task_id) is None

    def test_delete_running_task_returns_409(self, client: TestClient):
        """测试 DELETE /tasks/{task_id} 删除运行中任务返回 409。"""
        registry = TaskRegistry.get_instance()

        # 创建运行中任务
        task_id = registry.create_task(task_name="测试任务")
        from src.scraper import TaskStatus
        registry.update_task_status(task_id, TaskStatus.RUNNING)

        response = client.delete(f"/api/summaries/tasks/{task_id}")

        assert response.status_code == 409

    def test_delete_nonexistent_task_returns_404(self, client: TestClient):
        """测试 DELETE /tasks/{task_id} 不存在的任务返回 404。"""
        response = client.delete("/api/summaries/tasks/nonexistent-task-id")

        assert response.status_code == 404
