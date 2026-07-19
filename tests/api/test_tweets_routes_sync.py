"""推文 API 路由测试（同步版本）。

测试推文列表和详情 API 端点。
使用 TestClient 的同步接口，通过依赖覆盖确保数据库隔离。
"""

import os
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.config import clear_settings_cache
from src.main import app
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN

@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级 FastAPI 测试客户端，禁用调度器避免 lifespan 阻塞。"""
    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()
    app.dependency_overrides[get_current_admin_user] = lambda: BOOTSTRAP_ADMIN
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_current_admin_user, None)
    clear_settings_cache()


@pytest.fixture(autouse=True)
def tweet_file_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Route tests now exercise the file-backed tweet read provider."""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def seed_test_tweets(tweet_file_data_root: Path) -> list[Tweet]:
    """准备测试推文数据。"""
    now = datetime.now(UTC)
    tweets = [
        Tweet(
            tweet_id="tweet1",
            text="First test tweet",
            created_at=now,
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        Tweet(
            tweet_id="tweet2",
            text="Second test tweet",
            created_at=now - timedelta(seconds=1),
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        Tweet(
            tweet_id="tweet3",
            text="Tweet from user2",
            created_at=now - timedelta(seconds=2),
            author_username="user2",
            author_display_name="User Two",
            media=None,
        ),
    ]

    import asyncio

    asyncio.run(
        FileTweetStore(tweet_file_data_root).save_tweets(
            tweets, early_stop_threshold=0
        )
    )

    return tweets


class TestTweetListAPI:
    """测试推文列表 API。"""

    def test_list_tweets_default_params(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试默认参数获取推文列表。"""
        response = client.get("/api/tweets")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data

        # 验证分页参数
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total"] == 3
        assert data["total_pages"] == 1
        assert len(data["items"]) == 3

    def test_list_tweets_with_pagination(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试分页参数。"""
        response = client.get("/api/tweets?page=1&page_size=2")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total"] == 3
        assert data["total_pages"] == 2  # ceil(3/2) = 2
        assert len(data["items"]) == 2

    def test_list_tweets_filter_by_author(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试按作者筛选。"""
        response = client.get("/api/tweets?author=user1")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        assert all(item["author_username"] == "user1" for item in data["items"])

    def test_list_tweets_empty_author_filter(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试筛选不存在的作者。"""
        response = client.get("/api/tweets?author=nonexistent")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0

    def test_list_tweets_invalid_page(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试无效的页码。"""
        response = client.get("/api/tweets?page=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_list_tweets_invalid_page_size(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试无效的 page_size。"""
        response = client.get("/api/tweets?page_size=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        response = client.get("/api/tweets?page_size=101")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_list_tweets_ordering(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试推文按时间倒序排列。"""
        response = client.get("/api/tweets")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        items = data["items"]

        # 验证时间倒序：tweet1（最新） > tweet2 > tweet3（最早）
        assert items[0]["tweet_id"] == "tweet1"
        assert items[1]["tweet_id"] == "tweet2"
        assert items[2]["tweet_id"] == "tweet3"


class TestTweetDetailAPI:
    """测试推文详情 API。"""

    def test_get_tweet_detail_success(
        self, client: TestClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试成功获取推文详情。"""
        response = client.get("/api/tweets/tweet1")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["tweet_id"] == "tweet1"
        assert data["text"] == "First test tweet"
        assert data["author_username"] == "user1"
        assert data["author_display_name"] == "User One"
        assert "media" in data

    def test_get_tweet_detail_not_found(self, client: TestClient) -> None:
        """测试获取不存在的推文。"""
        response = client.get("/api/tweets/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND

        data = response.json()
        assert "detail" in data
