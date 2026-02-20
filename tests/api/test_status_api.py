"""系统状态概览 API 集成测试。

测试完整调用链：HTTP 请求 → 认证 → 聚合查询 → 响应格式验证。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database.models import Base, ScraperFollow, ScraperScheduleConfig
from src.main import app
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.topic.infrastructure.models import TopicOrm, TopicSummaryTaskOrm
from src.user.domain.models import UserDomain


@pytest.fixture
async def status_test_engine():
    """独立的异步数据库引擎 fixture（StaticPool 确保内存 SQLite 多 session 共享连接）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def status_test_session_maker(status_test_engine):
    """异步 session maker fixture。"""
    return async_sessionmaker(
        status_test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def status_test_session(status_test_session_maker):
    """独立的异步数据库会话 fixture（用于数据种子和旧式 DI 覆盖）。"""
    async with status_test_session_maker() as session:
        yield session


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
def mock_start_time() -> datetime:
    """模拟的服务启动时间。"""
    return datetime(2026, 2, 19, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def status_client(status_test_session_maker, mock_user, mock_start_time):
    """Status API 集成测试客户端（带认证 + mock scheduler/start_time）。"""
    from src.user.api.auth import get_current_user

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock scheduler: running, has a scraper_job
    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    mock_job = MagicMock()
    mock_job.next_run_time = datetime(2026, 2, 19, 20, 0, 0, tzinfo=timezone.utc)
    mock_scheduler.get_job.return_value = mock_job

    transport = ASGITransport(app=app)
    with (
        patch("src.api.routes.status.get_scheduler", return_value=mock_scheduler),
        patch(
            "src.api.routes.status.get_server_start_time",
            return_value=mock_start_time,
        ),
        patch(
            "src.database.async_session.get_async_session_maker",
            return_value=status_test_session_maker,
        ),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def status_client_stopped_scheduler(
    status_test_session_maker, mock_user, mock_start_time
):
    """Status API 客户端（scheduler=None，模拟停止状态）。"""
    from src.user.api.auth import get_current_user

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    with (
        patch("src.api.routes.status.get_scheduler", return_value=None),
        patch(
            "src.api.routes.status.get_server_start_time",
            return_value=mock_start_time,
        ),
        patch(
            "src.database.async_session.get_async_session_maker",
            return_value=status_test_session_maker,
        ),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def seed_status_data(status_test_session: AsyncSession):
    """准备 Status 测试数据。

    - 5 条推文（3 条今日、2 条昨天）
    - 3 条摘要（2 条推文待摘要）
    - 3 个关注账号（2 活跃 + 1 非活跃）
    - 2 个主题
    - 1 个主题摘要任务（completed）
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 今日推文
    for i in range(3):
        tweet = TweetOrm(
            tweet_id=f"today_tweet_{i}",
            text=f"Today tweet {i}",
            created_at=today_start + timedelta(hours=i + 1),
            author_username="alice",
            author_display_name="Alice",
            media=None,
        )
        status_test_session.add(tweet)

    # 昨日推文
    for i in range(2):
        tweet = TweetOrm(
            tweet_id=f"yesterday_tweet_{i}",
            text=f"Yesterday tweet {i}",
            created_at=today_start - timedelta(hours=i + 1),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        )
        status_test_session.add(tweet)

    await status_test_session.flush()

    # 摘要（覆盖 3 条推文，2 条无摘要）
    for i in range(3):
        summary = SummaryOrm(
            summary_id=str(uuid4()),
            tweet_id=f"today_tweet_{i}",
            summary_text=f"摘要 {i}",
            translation_text=f"Translation {i}",
            model_provider="minimax",
            model_name="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=False,
            is_generated_summary=True,
            content_hash=f"status_hash_{i}",
        )
        status_test_session.add(summary)

    # 关注账号
    status_test_session.add(
        ScraperFollow(
            username="alice",
            reason="test",
            added_by="admin",
            is_active=True,
        )
    )
    status_test_session.add(
        ScraperFollow(
            username="bob",
            reason="test",
            added_by="admin",
            is_active=True,
        )
    )
    status_test_session.add(
        ScraperFollow(
            username="charlie",
            reason="test",
            added_by="admin",
            is_active=False,
        )
    )

    # 主题
    topic1 = TopicOrm(name="Topic A", description="Description A")
    topic2 = TopicOrm(name="Topic B", description="Description B")
    status_test_session.add(topic1)
    status_test_session.add(topic2)
    await status_test_session.flush()

    # 主题摘要任务（completed）
    task = TopicSummaryTaskOrm(
        topic_id=topic1.id,
        time_span_hours=24,
        deadline=now,
        status="completed",
        completed_at=now - timedelta(hours=1),
    )
    status_test_session.add(task)
    await status_test_session.commit()


class TestStatusOverviewSuccess:
    """测试成功场景。"""

    async def test_full_response_structure(
        self, status_client: AsyncClient, seed_status_data
    ):
        """完整调用链成功：200 + 所有 6 个顶级字段存在。"""
        response = await status_client.get("/api/status/overview")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # 验证 6 个顶级字段
        assert "tweets" in data
        assert "follows" in data
        assert "summaries" in data
        assert "topics" in data
        assert "scheduler" in data
        assert "system" in data

    async def test_tweet_stats(
        self, status_client: AsyncClient, seed_status_data
    ):
        """推文统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        tweets = data["tweets"]
        assert tweets["total"] == 5
        assert tweets["today_count"] == 3
        assert tweets["latest_tweet_at"] is not None

    async def test_follow_stats(
        self, status_client: AsyncClient, seed_status_data
    ):
        """关注统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        follows = data["follows"]
        assert follows["total"] == 3
        assert follows["active"] == 2
        assert follows["inactive"] == 1

    async def test_summary_stats(
        self, status_client: AsyncClient, seed_status_data
    ):
        """摘要统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        summaries = data["summaries"]
        assert summaries["total"] == 3
        # 5 条推文 - 3 条有摘要 = 2 条待摘要
        assert summaries["pending_tweets"] == 2

    async def test_topic_stats(
        self, status_client: AsyncClient, seed_status_data
    ):
        """主题统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        topics = data["topics"]
        assert topics["total"] == 2
        assert topics["latest_summary_at"] is not None
        assert topics["latest_summary_status"] == "completed"

    async def test_scheduler_running(
        self, status_client: AsyncClient, seed_status_data
    ):
        """调度器 running 状态正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        scheduler = data["scheduler"]
        assert scheduler["status"] == "running"
        assert scheduler["next_run_time"] is not None
        assert isinstance(scheduler["interval_seconds"], int)

    async def test_scheduler_stopped(
        self, status_client_stopped_scheduler: AsyncClient, seed_status_data
    ):
        """调度器 stopped 状态正确。"""
        response = await status_client_stopped_scheduler.get(
            "/api/status/overview"
        )
        data = response.json()

        scheduler = data["scheduler"]
        assert scheduler["status"] == "stopped"
        assert scheduler["next_run_time"] is None

    async def test_system_stats(
        self, status_client: AsyncClient, seed_status_data
    ):
        """系统统计字段存在。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        system = data["system"]
        assert "server_start_time" in system
        assert system["server_start_time"] is not None
        assert "database_size_mb" in system


class TestStatusOverviewEmptyDB:
    """测试空数据库场景。"""

    async def test_empty_database(self, status_client: AsyncClient):
        """空数据库：所有计数为 0，可选字段为 None。"""
        response = await status_client.get("/api/status/overview")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["tweets"]["total"] == 0
        assert data["tweets"]["latest_tweet_at"] is None
        assert data["tweets"]["today_count"] == 0

        assert data["follows"]["total"] == 0
        assert data["follows"]["active"] == 0
        assert data["follows"]["inactive"] == 0

        assert data["summaries"]["total"] == 0
        assert data["summaries"]["pending_tweets"] == 0

        assert data["topics"]["total"] == 0
        assert data["topics"]["latest_summary_at"] is None
        assert data["topics"]["latest_summary_status"] is None
