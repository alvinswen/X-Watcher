"""摘要读取 API 端点集成测试。"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import clear_settings_cache
from src.main import app
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.models import SummaryOrm
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN


@pytest.fixture(autouse=True)
def override_auth():
    """覆盖管理员认证依赖，避免 401。"""
    app.dependency_overrides[get_current_admin_user] = lambda: BOOTSTRAP_ADMIN
    yield
    app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.fixture(autouse=True)
def setup_test_env():
    """设置测试环境变量。"""
    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()

    yield

    os.environ.pop("SCRAPER_ENABLED", None)
    clear_settings_cache()


@pytest.fixture(scope="class")
def client():
    """Class-scoped TestClient，同一 class 内共享。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_summary_record():
    """示例摘要记录。"""
    return SummaryRecord(
        summary_id="test-summary-id",
        tweet_id="test-tweet-id",
        summary_text="这是一条测试摘要，包含了足够的字符以满足最小长度要求。该摘要描述了一条关于人工智能技术发展的重要推文内容。",
        translation_text="This is a test summary with enough characters to meet the minimum length requirement.",
        model_provider="agent",
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


class TestGetTweetSummaryEndpoint:
    """测试查询单条推文摘要端点。"""

    async def test_get_existing_summary_returns_data(
        self,
        client: TestClient,
        async_session,
        sample_summary_record,
    ):
        """测试 GET /tweets/{id} 存在返回摘要。"""
        orm_record = SummaryOrm.from_domain(sample_summary_record)
        async_session.add(orm_record)
        await async_session.commit()

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
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_summary_by_tweet = AsyncMock(return_value=None)

        with patch(
            "src.summarization.api.routes.get_async_session_maker",
            return_value=lambda: mock_session,
        ), patch(
            "src.summarization.api.routes.get_summary_repo",
            return_value=mock_repo,
        ):
            response = client.get("/api/summaries/tweets/nonexistent-tweet")

        assert response.status_code == 404
