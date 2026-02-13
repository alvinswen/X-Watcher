"""推文 API 路由测试（同步版本）。

测试推文列表和详情 API 端点。
使用 TestClient 的同步接口，通过依赖覆盖确保数据库隔离。
"""

import os
from datetime import datetime, timezone

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import clear_settings_cache
from src.database.async_session import get_db_session
from src.database.models import Base
from src.main import app
from src.scraper.infrastructure.models import TweetOrm

# 导入所有 ORM 模型以确保表注册
from src.scraper.infrastructure.models import DeduplicationGroupOrm  # noqa: F401
from src.summarization.infrastructure.models import SummaryOrm  # noqa: F401


# 同步测试用引擎
_sync_test_engine = create_engine(
    "sqlite:///",
    connect_args={"check_same_thread": False},
)
_SyncTestSession = sessionmaker(
    autocommit=False, autoflush=False, bind=_sync_test_engine
)


@pytest.fixture(scope="module")
def _isolated_db():
    """创建隔离的测试数据库并覆盖 FastAPI 依赖（模块级共享）。"""
    # 创建表
    Base.metadata.create_all(bind=_sync_test_engine)

    # 创建同步 session（供 seed 使用）
    sync_session = _SyncTestSession()

    # 覆盖 get_db_session 依赖，返回异步包装
    # TestClient 内部会创建事件循环来运行异步依赖
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async_engine = create_async_engine(
        "sqlite+aiosqlite:///",
        connect_args={"check_same_thread": False},
    )

    async def _setup_async():
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup_async())

    async_session_maker = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 共享一个 session 实例使 seed 和 API 路由看到同一数据
    _shared_session = None

    async def override_get_db_session():
        nonlocal _shared_session
        if _shared_session is None:
            _shared_session = async_session_maker()
        yield _shared_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    yield async_session_maker, loop

    # 清理
    app.dependency_overrides.pop(get_db_session, None)

    async def _cleanup():
        if _shared_session:
            await _shared_session.close()
        await async_engine.dispose()

    loop.run_until_complete(_cleanup())
    loop.close()

    sync_session.close()
    Base.metadata.drop_all(bind=_sync_test_engine)


@pytest.fixture(scope="module")
def client(_isolated_db) -> TestClient:
    """模块级 FastAPI 测试客户端，禁用调度器避免 lifespan 阻塞。"""
    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()
    with TestClient(app) as test_client:
        yield test_client
    clear_settings_cache()


@pytest.fixture(scope="module")
def seed_test_tweets(_isolated_db) -> list[TweetOrm]:
    """准备测试推文数据（模块级共享）。"""
    from datetime import timedelta

    session_maker, loop = _isolated_db
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
            created_at=now - timedelta(seconds=1),
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        TweetOrm(
            tweet_id="tweet3",
            text="Tweet from user2",
            created_at=now - timedelta(seconds=2),
            author_username="user2",
            author_display_name="User Two",
            media=None,
        ),
    ]

    async def insert():
        async with session_maker() as session:
            for tweet in tweets:
                session.add(tweet)
            await session.commit()
            for tweet in tweets:
                await session.refresh(tweet)

    loop.run_until_complete(insert())

    return tweets


class TestTweetListAPI:
    """测试推文列表 API。"""

    def test_list_tweets_default_params(
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
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
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
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
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试按作者筛选。"""
        response = client.get("/api/tweets?author=user1")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 2
        assert all(item["author_username"] == "user1" for item in data["items"])

    def test_list_tweets_empty_author_filter(
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试筛选不存在的作者。"""
        response = client.get("/api/tweets?author=nonexistent")

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0

    def test_list_tweets_invalid_page(
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试无效的页码。"""
        response = client.get("/api/tweets?page=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_tweets_invalid_page_size(
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
    ) -> None:
        """测试无效的 page_size。"""
        response = client.get("/api/tweets?page_size=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        response = client.get("/api/tweets?page_size=101")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_tweets_ordering(
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
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
        self, client: TestClient, seed_test_tweets: list[TweetOrm]
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
