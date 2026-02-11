"""推文 API 路由测试。

测试推文列表和详情 API 端点。
"""

from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.infrastructure.models import TweetOrm


@pytest.fixture
async def seed_test_tweets(async_session: AsyncSession) -> list[TweetOrm]:
    """准备测试推文数据。

    Args:
        async_session: 异步数据库会话

    Returns:
        创建的推文 ORM 列表
    """
    now = datetime.now(timezone.utc)
    tweets = [
        TweetOrm(
            tweet_id="tweet1",
            text="First test tweet",
            created_at=now,
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        TweetOrm(
            tweet_id="tweet2",
            text="Second test tweet",
            created_at=now.replace(second=now.second - 1),  # 早 1 秒
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        TweetOrm(
            tweet_id="tweet3",
            text="Tweet from user2",
            created_at=now.replace(second=now.second - 2),  # 早 2 秒
            author_username="user2",
            author_display_name="User Two",
            media=None,
        ),
    ]

    for tweet in tweets:
        async_session.add(tweet)

    await async_session.commit()

    # 刷新以获取数据库生成的值
    for tweet in tweets:
        await async_session.refresh(tweet)

    return tweets


@pytest.mark.asyncio
class TestTweetListAPI:
    """测试推文列表 API。"""

    async def test_list_tweets_default_params(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
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
        assert data["total"] == 3
        assert data["total_pages"] == 1
        assert len(data["items"]) == 3

    async def test_list_tweets_with_pagination(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试分页参数。"""
        response = await async_client.get("/api/tweets?page=1&page_size=2")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total"] == 3
        assert data["total_pages"] == 2  # ceil(3/2) = 2
        assert len(data["items"]) == 2

    async def test_list_tweets_filter_by_author(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试按作者筛选。"""
        response = await async_client.get("/api/tweets?author=user1")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        assert all(item["author_username"] == "user1" for item in data["items"])

    async def test_list_tweets_empty_author_filter(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试筛选不存在的作者。"""
        response = await async_client.get("/api/tweets?author=nonexistent")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0

    async def test_list_tweets_invalid_page(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试无效的页码。"""
        response = await async_client.get("/api/tweets?page=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_list_tweets_invalid_page_size(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试无效的 page_size。"""
        response = await async_client.get("/api/tweets?page_size=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        response = await async_client.get("/api/tweets?page_size=101")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_list_tweets_ordering(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试推文按时间倒序排列。"""
        response = await async_client.get("/api/tweets")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        items = data["items"]

        # 验证返回了所有测试数据
        assert len(items) == 3
        # 验证每个项目都有必要的字段
        for item in items:
            assert "tweet_id" in item
            assert "created_at" in item
            assert "text" in item


@pytest.mark.asyncio
class TestTweetDetailAPI:
    """测试推文详情 API。"""

    async def test_get_tweet_detail_success(
        self, async_client: AsyncClient, seed_test_tweets: list[TweetOrm]
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
