"""推文 API 路由测试。

测试推文列表和详情 API 端点。
"""

from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import pytest
from fastapi import status
from httpx import AsyncClient

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore


@pytest.fixture(autouse=True)
def tweet_file_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Route tests now exercise the file-backed tweet read provider."""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
async def seed_test_tweets(tweet_file_data_root: Path) -> list[Tweet]:
    """准备测试推文数据。

    Args:
        tweet_file_data_root: 文件数据层根目录

    Returns:
        创建的推文领域对象列表
    """
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
            created_at=now - timedelta(days=1),  # 早 1 天
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        Tweet(
            tweet_id="tweet3",
            text="Tweet from user2",
            created_at=now - timedelta(days=2),  # 早 2 天
            author_username="user2",
            author_display_name="User Two",
            media=None,
        ),
        Tweet(
            tweet_id="tweet4",
            text="Old tweet from user2",
            created_at=now - timedelta(days=3),  # 早 3 天
            author_username="user2",
            author_display_name="User Two",
            media=None,
        ),
    ]

    await FileTweetStore(tweet_file_data_root).save_tweets(
        tweets, early_stop_threshold=0
    )
    return tweets


def _query_dt(dt: datetime) -> str:
    """Render an aware UTC datetime safely for raw query-string interpolation."""
    return dt.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
class TestTweetListAPI:
    """测试推文列表 API。"""

    async def test_list_tweets_default_params(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试默认参数获取推文列表。"""
        response = await async_client.get("/api/tweets")

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
        assert data["total"] == 4
        assert data["total_pages"] == 1
        assert len(data["items"]) == 4

    async def test_list_tweets_with_pagination(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试分页参数。"""
        response = await async_client.get("/api/tweets?page=1&page_size=2")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total"] == 4
        assert data["total_pages"] == 2  # ceil(4/2) = 2
        assert len(data["items"]) == 2

    async def test_list_tweets_filter_by_author(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试按作者筛选。"""
        response = await async_client.get("/api/tweets?author=user1")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        assert all(item["author_username"] == "user1" for item in data["items"])

    async def test_list_tweets_empty_author_filter(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试筛选不存在的作者。"""
        response = await async_client.get("/api/tweets?author=nonexistent")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0

    async def test_list_tweets_invalid_page(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试无效的页码。"""
        response = await async_client.get("/api/tweets?page=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_list_tweets_invalid_page_size(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试无效的 page_size。"""
        response = await async_client.get("/api/tweets?page_size=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        response = await async_client.get("/api/tweets?page_size=101")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_list_tweets_ordering(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试推文按时间倒序排列。"""
        response = await async_client.get("/api/tweets")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        items = data["items"]

        # 验证返回了所有测试数据
        assert len(items) == 4
        # 验证每个项目都有必要的字段
        for item in items:
            assert "tweet_id" in item
            assert "created_at" in item
            assert "text" in item

    # ========== 时间范围过滤测试 (Task 2.2) ==========

    async def test_list_tweets_filter_by_created_after(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试仅提供 created_after 的单边过滤（含）。"""
        # 使用 tweet2 的创建时间作为 created_after，应返回 tweet1 和 tweet2
        created_after = _query_dt(seed_test_tweets[1].created_at)
        response = await async_client.get(f"/api/tweets?created_after={created_after}")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        tweet_ids = {item["tweet_id"] for item in data["items"]}
        assert tweet_ids == {"tweet1", "tweet2"}

    async def test_list_tweets_filter_by_created_before(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试仅提供 created_before 的单边过滤（不含）。"""
        # 使用 tweet2 的创建时间作为 created_before，应返回 tweet3 和 tweet4
        created_before = _query_dt(seed_test_tweets[1].created_at)
        response = await async_client.get(f"/api/tweets?created_before={created_before}")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        tweet_ids = {item["tweet_id"] for item in data["items"]}
        assert tweet_ids == {"tweet3", "tweet4"}

    async def test_list_tweets_filter_by_date_range(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试同时提供 created_after 和 created_before 的双边过滤。"""
        # [tweet3.created_at, tweet1.created_at) → 应返回 tweet2 和 tweet3
        created_after = _query_dt(seed_test_tweets[2].created_at)
        created_before = _query_dt(seed_test_tweets[0].created_at)
        response = await async_client.get(
            f"/api/tweets?created_after={created_after}&created_before={created_before}"
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        assert data["total_pages"] == 1
        tweet_ids = {item["tweet_id"] for item in data["items"]}
        assert tweet_ids == {"tweet2", "tweet3"}

    # ========== 组合过滤与分页测试 (Task 2.3) ==========

    async def test_list_tweets_filter_combined_author_and_date_range(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试作者筛选与时间范围过滤组合使用。"""
        # author=user1 AND created_after=tweet1.created_at → 仅 tweet1
        created_after = _query_dt(seed_test_tweets[0].created_at)
        response = await async_client.get(
            f"/api/tweets?author=user1&created_after={created_after}"
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["tweet_id"] == "tweet1"
        assert data["items"][0]["author_username"] == "user1"

    async def test_list_tweets_date_range_with_pagination(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试时间范围过滤与分页参数的组合。"""
        # created_after=tweet3.created_at → 3 条结果 (tweet1, tweet2, tweet3)
        created_after = _query_dt(seed_test_tweets[2].created_at)
        response = await async_client.get(
            f"/api/tweets?created_after={created_after}&page_size=1&page=1"
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 3
        assert data["total_pages"] == 3
        assert data["page"] == 1
        assert len(data["items"]) == 1

        # 验证第 2 页返回不同的推文
        response2 = await async_client.get(
            f"/api/tweets?created_after={created_after}&page_size=1&page=2"
        )
        data2 = response2.json()
        assert data2["total"] == 3
        assert len(data2["items"]) == 1
        assert data2["items"][0]["tweet_id"] != data["items"][0]["tweet_id"]

    # ========== 输入验证与向后兼容测试 (Task 2.4) ==========

    async def test_list_tweets_invalid_date_format(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试无效日期格式返回 422。"""
        response = await async_client.get("/api/tweets?created_after=not-a-date")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_list_tweets_invalid_date_range(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试 created_after >= created_before 返回 422。"""
        now = datetime.now(UTC)
        # 使用 URL 安全的日期格式（用 %2B 编码 +，或直接构造不带 +00:00 的格式）
        later = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        earlier = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # created_after 晚于 created_before
        response = await async_client.get(
            f"/api/tweets?created_after={later}&created_before={earlier}"
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        data = response.json()
        assert "时间范围无效" in data["detail"]

        # created_after 等于 created_before
        same_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        response2 = await async_client.get(
            f"/api/tweets?created_after={same_time}&created_before={same_time}"
        )
        assert response2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_list_tweets_no_date_params_backward_compatible(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试不提供时间参数时行为与原来完全一致。"""
        response = await async_client.get("/api/tweets")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 4
        assert len(data["items"]) == 4
        # 验证响应结构完整
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data


@pytest.mark.asyncio
class TestTweetDetailAPI:
    """测试推文详情 API。"""

    async def test_get_tweet_detail_success(
        self, async_client: AsyncClient, seed_test_tweets: list[Tweet]
    ) -> None:
        """测试成功获取推文详情。"""
        response = await async_client.get("/api/tweets/tweet1")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["tweet_id"] == "tweet1"
        assert data["text"] == "First test tweet"
        assert data["author_username"] == "user1"
        assert data["author_display_name"] == "User One"
        assert "media" in data

    async def test_get_tweet_detail_not_found(
        self, async_client: AsyncClient
    ) -> None:
        """测试获取不存在的推文。"""
        response = await async_client.get("/api/tweets/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND

        data = response.json()
        assert "detail" in data
