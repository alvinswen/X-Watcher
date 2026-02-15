"""Feed API 集成测试。

测试完整调用链：HTTP 请求 → 认证 → 查询 → 响应格式验证。
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import clear_settings_cache
from src.database.models import Base
from src.main import app
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.user.domain.models import UserDomain


@pytest.fixture
async def feed_test_session():
    """独立的异步数据库会话 fixture。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def mock_user() -> UserDomain:
    """创建模拟的认证用户。"""
    return UserDomain(
        id=1,
        name="testuser",
        email="test@example.com",
        is_admin=False,
        created_at=datetime.min,
    )


@pytest.fixture
async def feed_client(feed_test_session, mock_user):
    """Feed API 集成测试客户端（带认证）。"""
    from src.database.async_session import get_db_session
    from src.user.api.auth import get_current_user

    async def override_get_db_session():
        yield feed_test_session

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def feed_client_no_auth(feed_test_session):
    """无认证覆盖的客户端（用于测试 401 场景）。"""
    from src.database.async_session import get_async_session, get_db_session

    async def override_get_db_session():
        yield feed_test_session

    async def override_get_async_session():
        yield feed_test_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_async_session] = override_get_async_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_async_session, None)


@pytest.fixture
async def seed_feed_data(feed_test_session: AsyncSession):
    """准备 Feed 测试数据。"""
    now = datetime.now(timezone.utc)
    base_time = now - timedelta(hours=2)

    tweets = []
    for i in range(5):
        tweet = TweetOrm(
            tweet_id=f"api_tweet_{i}",
            text=f"Tweet number {i}",
            created_at=base_time + timedelta(minutes=50 - i * 10),
            db_created_at=base_time + timedelta(minutes=10 + i * 10),
            author_username="testuser",
            author_display_name="Test User",
            media=None,
        )
        feed_test_session.add(tweet)
        tweets.append(tweet)

    await feed_test_session.flush()

    summary = SummaryOrm(
        summary_id=str(uuid4()),
        tweet_id="api_tweet_0",
        summary_text="测试摘要",
        translation_text="测试翻译",
        model_provider="minimax",
        model_name="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        cached=False,
        is_generated_summary=True,
        content_hash="api_hash_0",
    )
    feed_test_session.add(summary)
    await feed_test_session.commit()

    return {"tweets": tweets, "base_time": base_time}


class TestFeedAPISuccess:
    """测试成功场景。"""

    async def test_feed_success_full_response(
        self, feed_client: AsyncClient, seed_feed_data
    ):
        """完整调用链成功：200 + 正确响应格式。"""
        base = seed_feed_data["base_time"]
        since = (base - timedelta(minutes=1)).isoformat()
        until = (base + timedelta(hours=2)).isoformat()

        response = await feed_client.get(
            "/api/feed", params={"since": since, "until": until}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "items" in data
        assert "count" in data
        assert "total" in data
        assert "since" in data
        assert "until" in data
        assert "has_more" in data
        assert data["count"] == len(data["items"])
        assert data["total"] == 5

    async def test_feed_response_metadata(
        self, feed_client: AsyncClient, seed_feed_data
    ):
        """验证响应元数据正确性。"""
        base = seed_feed_data["base_time"]
        since = base.isoformat()
        until = (base + timedelta(hours=2)).isoformat()

        response = await feed_client.get(
            "/api/feed", params={"since": since, "until": until, "limit": 3}
        )

        data = response.json()
        assert data["count"] == 3
        assert data["total"] == 5
        assert data["has_more"] is True

    async def test_feed_include_summary_false(
        self, feed_client: AsyncClient, seed_feed_data
    ):
        """include_summary=false 时 summary 字段为 null。"""
        base = seed_feed_data["base_time"]
        since = base.isoformat()
        until = (base + timedelta(hours=2)).isoformat()

        response = await feed_client.get(
            "/api/feed",
            params={
                "since": since,
                "until": until,
                "include_summary": "false",
            },
        )

        data = response.json()
        for item in data["items"]:
            assert item["summary_text"] is None
            assert item["translation_text"] is None


class TestFeedAPIAuth:
    """测试认证场景。"""

    async def test_no_auth_returns_401(
        self, feed_client_no_auth: AsyncClient, seed_feed_data
    ):
        """无认证凭证时返回 401。"""
        response = await feed_client_no_auth.get(
            "/api/feed",
            params={"since": "2025-01-01T00:00:00Z"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        data = response.json()
        assert "detail" in data

    async def test_invalid_api_key_returns_401(
        self, feed_client_no_auth: AsyncClient, seed_feed_data
    ):
        """无效 API Key 返回 401。"""
        response = await feed_client_no_auth.get(
            "/api/feed",
            params={"since": "2025-01-01T00:00:00Z"},
            headers={"X-API-Key": "invalid-key-12345"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestFeedAPIValidation:
    """测试参数验证。"""

    async def test_missing_since_returns_422(self, feed_client: AsyncClient):
        """缺少 since 参数返回 422。"""
        response = await feed_client.get("/api/feed")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_since_after_until_returns_422(self, feed_client: AsyncClient):
        """since > until 返回 422。"""
        response = await feed_client.get(
            "/api/feed",
            params={
                "since": "2025-01-02T00:00:00Z",
                "until": "2025-01-01T00:00:00Z",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        data = response.json()
        assert "时间区间无效" in data["detail"]

    async def test_invalid_datetime_format_returns_422(self, feed_client: AsyncClient):
        """无效时间格式返回 422。"""
        response = await feed_client.get(
            "/api/feed", params={"since": "not-a-date"}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestFeedAPILimitClamping:
    """测试 limit 钳位行为。"""

    async def test_limit_clamped_to_max(
        self, feed_client: AsyncClient, seed_feed_data
    ):
        """客户端 limit 超过系统配置时使用配置值。"""
        base = seed_feed_data["base_time"]
        since = base.isoformat()
        until = (base + timedelta(hours=2)).isoformat()

        # 设置 FEED_MAX_TWEETS=3 来测试钳位
        os.environ["FEED_MAX_TWEETS"] = "3"
        clear_settings_cache()

        try:
            response = await feed_client.get(
                "/api/feed",
                params={"since": since, "until": until, "limit": 999},
            )

            data = response.json()
            # 即使请求 limit=999，也最多返回 3 条
            assert data["count"] <= 3
        finally:
            os.environ.pop("FEED_MAX_TWEETS", None)
            clear_settings_cache()

    async def test_default_limit_uses_config(
        self, feed_client: AsyncClient, seed_feed_data
    ):
        """未提供 limit 时使用系统配置上限。"""
        base = seed_feed_data["base_time"]
        since = base.isoformat()
        until = (base + timedelta(hours=2)).isoformat()

        os.environ["FEED_MAX_TWEETS"] = "2"
        clear_settings_cache()

        try:
            response = await feed_client.get(
                "/api/feed", params={"since": since, "until": until}
            )

            data = response.json()
            assert data["count"] <= 2
            assert data["has_more"] is True
        finally:
            os.environ.pop("FEED_MAX_TWEETS", None)
            clear_settings_cache()
