"""搜索 API 集成测试。"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from src.config import clear_settings_cache
from src.main import app
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.user.domain.models import UserDomain


@pytest.fixture(autouse=True)
def file_data_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def mock_user() -> UserDomain:
    """模拟认证用户。"""
    return UserDomain(
        id=1,
        name="testuser",
        email="test@example.com",
        is_admin=False,
        created_at=datetime.min,
    )


@pytest.fixture
async def search_client(mock_user):
    """搜索 API 测试客户端（带认证）。"""
    from src.user.api.auth import get_current_user

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def search_client_no_auth():
    """无认证覆盖的客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def seed_search_data():
    """准备搜索测试数据。"""
    now = datetime.now(UTC)
    base_time = now - timedelta(hours=2)

    tweets = [
        Tweet(
            tweet_id="api_s1",
            text="Python is great for AI",
            created_at=base_time + timedelta(minutes=40),
            author_username="alice",
            author_display_name="Alice",
            referenced_tweet_text="deep learning frameworks",
            media=None,
        ),
        Tweet(
            tweet_id="api_s2",
            text="FastAPI web framework",
            created_at=base_time + timedelta(minutes=30),
            author_username="alice",
            author_display_name="Alice",
            media=None,
        ),
        Tweet(
            tweet_id="api_s3",
            text="Rust performance",
            created_at=base_time + timedelta(minutes=20),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        ),
    ]

    root = Path(os.environ["XWATCHER_DATA_ROOT"])
    await FileTweetStore(root).save_tweets(tweets, early_stop_threshold=0)

    summary = SummaryRecord(
        summary_id=str(uuid4()),
        tweet_id="api_s1",
        summary_text="Python AI 开发摘要",
        translation_text="Python AI summary",
        model_provider="minimax",
        model_name="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        cached=False,
        is_generated_summary=True,
        content_hash="api_hash_s1",
        created_at=now,
        updated_at=now,
    )
    await FileSummaryStore(root).seed([summary])

    return {"tweets": tweets, "base_time": base_time}


class TestSearchAPISuccess:
    """测试成功场景。"""

    async def test_search_basic(
        self, search_client: AsyncClient, seed_search_data
    ):
        """基本关键词搜索。"""
        response = await search_client.get(
            "/api/search/tweets", params={"q": "Python"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["count"] == 1
        assert data["q"] == "Python"
        assert data["page"] == 1
        assert data["items"][0]["tweet_id"] == "api_s1"

    async def test_search_response_format(
        self, search_client: AsyncClient, seed_search_data
    ):
        """验证响应格式完整性。"""
        response = await search_client.get(
            "/api/search/tweets", params={"q": "Python"}
        )

        data = response.json()
        assert "items" in data
        assert "count" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        assert "q" in data

        item = data["items"][0]
        assert "tweet_id" in item
        assert "text" in item
        assert "author_username" in item
        assert "created_at" in item
        assert "summary_text" in item
        assert "translation_text" in item
        assert "referenced_tweet_text" in item

    async def test_search_by_author(
        self, search_client: AsyncClient, seed_search_data
    ):
        """按作者筛选搜索。"""
        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "FastAPI", "author": "alice"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["tweet_id"] == "api_s2"

    async def test_search_by_authors(
        self, search_client: AsyncClient, seed_search_data
    ):
        """按多作者筛选搜索。"""
        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "performance", "authors": "alice,bob"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["author_username"] == "bob"

    async def test_search_with_time_range(
        self, search_client: AsyncClient, seed_search_data
    ):
        """带时间范围的搜索。"""
        base = seed_search_data["base_time"]
        since = (base + timedelta(minutes=25)).isoformat()
        until = (base + timedelta(minutes=45)).isoformat()

        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "Python", "since": since, "until": until},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1

    async def test_search_pagination(
        self, search_client: AsyncClient, seed_search_data
    ):
        """分页搜索。"""
        # 搜所有推文（"a" 匹配 great, FastAPI, performance）
        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "a", "page": 1, "page_size": 2},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 2
        assert data["total"] == 3
        assert data["total_pages"] == 2
        assert data["page"] == 1

    async def test_search_in_summary(
        self, search_client: AsyncClient, seed_search_data
    ):
        """搜索匹配摘要内容。"""
        response = await search_client.get(
            "/api/search/tweets", params={"q": "开发摘要"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["tweet_id"] == "api_s1"

    async def test_search_in_referenced_text(
        self, search_client: AsyncClient, seed_search_data
    ):
        """搜索匹配被引用推文内容。"""
        response = await search_client.get(
            "/api/search/tweets", params={"q": "deep learning"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["tweet_id"] == "api_s1"


class TestSearchAPIValidation:
    """测试参数验证。"""

    async def test_missing_q_returns_422(self, search_client: AsyncClient):
        """缺少 q 参数返回 422。"""
        response = await search_client.get("/api/search/tweets")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_empty_q_returns_422(self, search_client: AsyncClient):
        """空 q 参数返回 422。"""
        response = await search_client.get(
            "/api/search/tweets", params={"q": ""}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_author_and_authors_mutual_exclusive(
        self, search_client: AsyncClient
    ):
        """同时传 author 和 authors 返回 422。"""
        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "test", "author": "alice", "authors": "alice,bob"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_since_format_returns_422(
        self, search_client: AsyncClient
    ):
        """无效时间格式返回 422。"""
        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "test", "since": "not-a-date"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_since_after_until_returns_422(
        self, search_client: AsyncClient
    ):
        """since >= until 返回 422。"""
        response = await search_client.get(
            "/api/search/tweets",
            params={
                "q": "test",
                "since": "2025-01-02T00:00:00Z",
                "until": "2025-01-01T00:00:00Z",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_page_size_exceeds_max_returns_422(
        self, search_client: AsyncClient
    ):
        """page_size 超过 100 返回 422。"""
        response = await search_client.get(
            "/api/search/tweets",
            params={"q": "test", "page_size": 101},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestSearchAPIAuth:
    """测试认证。"""

    async def test_no_auth_returns_401(
        self, search_client_no_auth: AsyncClient, seed_search_data
    ):
        """无认证返回 401。"""
        response = await search_client_no_auth.get(
            "/api/search/tweets", params={"q": "test"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
