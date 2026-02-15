"""摘要修复 API 集成测试。

测试补缺（backfill）和重置（reset）端点。
改造后使用 SummarizationQueue 替代 BackgroundTasks + _run_summarization_task。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_db_session
from src.main import app
from src.scraper import TaskRegistry
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN, UserDomain


@pytest.fixture(autouse=True)
def reset_task_registry():
    """在每个测试前重置任务注册表。"""
    registry = TaskRegistry.get_instance()
    registry.clear_all()
    yield
    registry.clear_all()


@pytest.fixture
async def repair_session():
    """异步数据库会话（独立实例）。"""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from src.database.models import Base

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
def mock_summarization_queue():
    """Mock SummarizationQueue 单例，避免实际入队。"""
    mock_queue = Mock()
    mock_queue.enqueue = AsyncMock(return_value="mock-task-id")
    return mock_queue


@pytest.fixture
async def admin_client(repair_session, mock_summarization_queue):
    """带管理员认证的异步客户端。"""
    async def override_get_db_session():
        yield repair_session

    async def override_admin():
        return BOOTSTRAP_ADMIN

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_admin_user] = override_admin

    with patch(
        "src.summarization.services.summarization_queue.SummarizationQueue.get_instance",
        return_value=mock_summarization_queue,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.fixture
async def no_auth_client(repair_session):
    """无认证的异步客户端（用于测试 401）。"""
    async def override_get_db_session():
        yield repair_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides.pop(get_current_admin_user, None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
async def seed_tweets(repair_session: AsyncSession):
    """创建测试推文（3 条有摘要，2 条无摘要）。"""
    now = datetime.now(timezone.utc)

    # 5 条推文
    tweets = [
        TweetOrm(
            tweet_id=f"t{i}",
            text=f"Test tweet {i}",
            created_at=now - timedelta(hours=i),
            author_username="testuser",
            media=None,
        )
        for i in range(1, 6)
    ]
    for t in tweets:
        repair_session.add(t)
    await repair_session.flush()

    # t1, t2, t3 有摘要；t4, t5 无摘要
    for i in range(1, 4):
        repair_session.add(
            SummaryOrm(
                summary_id=f"s{i}",
                tweet_id=f"t{i}",
                summary_text=f"Summary {i}",
                translation_text=None,
                model_provider="minimax",
                model_name="test-model",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cost_usd=0.001,
                cached=False,
                is_generated_summary=True,
                content_hash=f"hash{i}",
            )
        )

    await repair_session.commit()
    return tweets


# ========== 补缺预览测试 ==========


@pytest.mark.asyncio
class TestBackfillPreview:
    """测试补缺预览端点。"""

    async def test_preview_returns_count(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """有缺失摘要的推文时返回正确数量。"""
        response = await admin_client.get("/api/summaries/backfill/preview")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tweet_count"] == 2  # t4, t5

    async def test_preview_with_time_range(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """时间范围过滤只返回范围内推文。"""
        now = datetime.now(timezone.utc)
        since = (now - timedelta(hours=5, minutes=30)).isoformat()
        until = (now - timedelta(hours=3, minutes=30)).isoformat()
        response = await admin_client.get(
            "/api/summaries/backfill/preview",
            params={"since": since, "until": until},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # t4 (4h ago) 和 t5 (5h ago) 无摘要，但只有 t4 和 t5 在范围内
        # since = now - 5.5h, until = now - 3.5h => t4(4h), t5(5h)
        assert data["tweet_count"] == 2

    async def test_preview_all_have_summaries(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """所有推文都有摘要时返回 0。"""
        now = datetime.now(timezone.utc)
        # 只查看 t1-t3 的时间范围（都有摘要）
        since = (now - timedelta(hours=3, minutes=30)).isoformat()
        until = (now + timedelta(hours=1)).isoformat()
        response = await admin_client.get(
            "/api/summaries/backfill/preview",
            params={"since": since, "until": until},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tweet_count"] == 0


# ========== 补缺执行测试 ==========


@pytest.mark.asyncio
class TestBackfillExecute:
    """测试补缺执行端点。"""

    async def test_backfill_returns_202(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """正常补缺返回 202 和任务信息。"""
        response = await admin_client.post(
            "/api/summaries/backfill", json={}
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert data["tweet_count"] == 2

    async def test_backfill_no_missing_returns_404(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """无需补缺时返回 404。"""
        now = datetime.now(timezone.utc)
        response = await admin_client.post(
            "/api/summaries/backfill",
            json={
                "since": (now - timedelta(hours=3, minutes=30)).isoformat(),
                "until": (now + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ========== 重置预览测试 ==========


@pytest.mark.asyncio
class TestResetPreview:
    """测试重置预览端点。"""

    async def test_preview_returns_count(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """时间范围内有推文时返回数量。"""
        now = datetime.now(timezone.utc)
        response = await admin_client.get(
            "/api/summaries/reset/preview",
            params={
                "since": (now - timedelta(hours=6)).isoformat(),
                "until": (now + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tweet_count"] == 5

    async def test_preview_empty_range(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """时间范围内无推文时返回 0。"""
        far_past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        less_far = (datetime.now(timezone.utc) - timedelta(days=364)).isoformat()
        response = await admin_client.get(
            "/api/summaries/reset/preview",
            params={"since": far_past, "until": less_far},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tweet_count"] == 0

    async def test_preview_invalid_time_range(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """since >= until 返回 422。"""
        now = datetime.now(timezone.utc)
        response = await admin_client.get(
            "/api/summaries/reset/preview",
            params={
                "since": (now + timedelta(hours=1)).isoformat(),
                "until": now.isoformat(),
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ========== 重置执行测试 ==========


@pytest.mark.asyncio
class TestResetExecute:
    """测试重置执行端点。"""

    async def test_reset_returns_202(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """正常重置返回 202 和任务信息。"""
        now = datetime.now(timezone.utc)
        response = await admin_client.post(
            "/api/summaries/reset",
            json={
                "since": (now - timedelta(hours=6)).isoformat(),
                "until": (now + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert data["tweet_count"] == 5

    async def test_reset_empty_range_returns_404(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """时间范围内无推文时返回 404。"""
        far_past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        less_far = (datetime.now(timezone.utc) - timedelta(days=364)).isoformat()
        response = await admin_client.post(
            "/api/summaries/reset",
            json={"since": far_past, "until": less_far},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_reset_invalid_time_range_returns_422(
        self, admin_client: AsyncClient, seed_tweets
    ):
        """since >= until 返回 422。"""
        now = datetime.now(timezone.utc)
        response = await admin_client.post(
            "/api/summaries/reset",
            json={
                "since": (now + timedelta(hours=1)).isoformat(),
                "until": now.isoformat(),
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ========== 认证测试 ==========


@pytest.mark.asyncio
class TestAuthRequired:
    """测试所有新端点都需要认证。"""

    async def test_backfill_preview_no_auth(
        self, no_auth_client: AsyncClient, seed_tweets
    ):
        """补缺预览无凭证返回 401。"""
        response = await no_auth_client.get("/api/summaries/backfill/preview")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    async def test_backfill_execute_no_auth(
        self, no_auth_client: AsyncClient, seed_tweets
    ):
        """补缺执行无凭证返回 401。"""
        response = await no_auth_client.post(
            "/api/summaries/backfill", json={}
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    async def test_reset_preview_no_auth(
        self, no_auth_client: AsyncClient, seed_tweets
    ):
        """重置预览无凭证返回 401。"""
        now = datetime.now(timezone.utc)
        response = await no_auth_client.get(
            "/api/summaries/reset/preview",
            params={
                "since": (now - timedelta(hours=1)).isoformat(),
                "until": now.isoformat(),
            },
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    async def test_reset_execute_no_auth(
        self, no_auth_client: AsyncClient, seed_tweets
    ):
        """重置执行无凭证返回 401。"""
        now = datetime.now(timezone.utc)
        response = await no_auth_client.post(
            "/api/summaries/reset",
            json={
                "since": (now - timedelta(hours=1)).isoformat(),
                "until": now.isoformat(),
            },
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
