"""主题最新摘要快捷接口集成测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database.models import Base
from src.main import app
from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
)
from src.topic.domain.models import TopicSummaryTaskStatus
from src.user.domain.models import UserDomain


@pytest.fixture
async def ls_test_session():
    """独立的异步数据库会话。"""
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
    """模拟认证用户（非 admin）。"""
    return UserDomain(
        id=1,
        name="testuser",
        email="test@example.com",
        is_admin=False,
        created_at=datetime.min,
    )


@pytest.fixture
async def ls_client(ls_test_session, mock_user):
    """最新摘要 API 测试客户端（带用户级认证）。"""
    from src.database.async_session import get_db_session
    from src.user.api.auth import get_current_user

    async def override_get_db_session():
        yield ls_test_session

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def _create_topic_with_completed_task(
    session: AsyncSession,
    topic_name: str = "AI 热点",
    completed_at: datetime | None = None,
    summary_content: str = "这是一段摘要内容",
    tweet_count: int = 10,
    account_count: int = 3,
) -> tuple[TopicOrm, TopicSummaryTaskOrm, TopicSummaryOrm]:
    """创建带有已完成摘要任务的主题。"""
    topic = TopicOrm.from_domain(name=topic_name, description="测试主题")
    session.add(topic)
    await session.flush()

    if completed_at is None:
        completed_at = datetime.now(timezone.utc)

    task = TopicSummaryTaskOrm(
        topic_id=topic.id,
        time_span_hours=24,
        deadline=datetime.now(timezone.utc),
        status=TopicSummaryTaskStatus.completed.value,
        started_at=completed_at - timedelta(minutes=5),
        completed_at=completed_at,
    )
    session.add(task)
    await session.flush()

    summary = TopicSummaryOrm(
        task_id=task.id,
        content=summary_content,
        llm_provider="openai",
        llm_model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.005,
        tweet_count=tweet_count,
        account_count=account_count,
    )
    session.add(summary)
    await session.commit()

    return topic, task, summary


class TestLatestSummarySuccess:
    """正常返回最新摘要。"""

    async def test_returns_latest_summary(self, ls_client: AsyncClient, ls_test_session):
        """创建一个 completed 任务+摘要，验证响应字段完整。"""
        topic, task, summary = await _create_topic_with_completed_task(
            ls_test_session,
            summary_content="AI 领域最新动态摘要",
            tweet_count=15,
            account_count=5,
        )

        response = await ls_client.get(f"/api/topics/{topic.id}/latest-summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["topic_id"] == topic.id
        assert data["topic_name"] == "AI 热点"
        assert data["content"] == "AI 领域最新动态摘要"
        assert data["time_span_hours"] == 24
        assert data["tweet_count"] == 15
        assert data["account_count"] == 5
        assert data["task_id"] == task.id
        assert "generated_at" in data
        assert "deadline" in data

    async def test_returns_latest_when_multiple_completed(
        self, ls_client: AsyncClient, ls_test_session
    ):
        """多个已完成摘要时返回最新的。"""
        now = datetime.now(timezone.utc)

        # 创建主题
        topic = TopicOrm.from_domain(name="多摘要主题", description="测试")
        ls_test_session.add(topic)
        await ls_test_session.flush()

        # 较早的已完成任务
        old_task = TopicSummaryTaskOrm(
            topic_id=topic.id,
            time_span_hours=12,
            deadline=now - timedelta(hours=24),
            status=TopicSummaryTaskStatus.completed.value,
            started_at=now - timedelta(hours=25),
            completed_at=now - timedelta(hours=24),
        )
        ls_test_session.add(old_task)
        await ls_test_session.flush()

        old_summary = TopicSummaryOrm(
            task_id=old_task.id,
            content="旧摘要",
            llm_provider="openai",
            llm_model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.005,
            tweet_count=5,
            account_count=2,
        )
        ls_test_session.add(old_summary)

        # 较新的已完成任务
        new_task = TopicSummaryTaskOrm(
            topic_id=topic.id,
            time_span_hours=24,
            deadline=now,
            status=TopicSummaryTaskStatus.completed.value,
            started_at=now - timedelta(minutes=5),
            completed_at=now,
        )
        ls_test_session.add(new_task)
        await ls_test_session.flush()

        new_summary = TopicSummaryOrm(
            task_id=new_task.id,
            content="最新摘要",
            llm_provider="openai",
            llm_model="gpt-4o",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            cost_usd=0.01,
            tweet_count=20,
            account_count=8,
        )
        ls_test_session.add(new_summary)
        await ls_test_session.commit()

        response = await ls_client.get(f"/api/topics/{topic.id}/latest-summary")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["content"] == "最新摘要"
        assert data["task_id"] == new_task.id
        assert data["tweet_count"] == 20
        assert data["account_count"] == 8


class TestLatestSummary404:
    """404 场景测试。"""

    async def test_topic_not_found(self, ls_client: AsyncClient):
        """主题不存在 → 404。"""
        response = await ls_client.get("/api/topics/99999/latest-summary")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "主题不存在" in response.json()["detail"]

    async def test_no_completed_summary(self, ls_client: AsyncClient, ls_test_session):
        """无已完成摘要 → 404。"""
        # 创建主题
        topic = TopicOrm.from_domain(name="空主题", description="无摘要")
        ls_test_session.add(topic)
        await ls_test_session.flush()

        # 只创建 pending 任务
        pending_task = TopicSummaryTaskOrm(
            topic_id=topic.id,
            time_span_hours=24,
            deadline=datetime.now(timezone.utc),
            status=TopicSummaryTaskStatus.pending.value,
        )
        ls_test_session.add(pending_task)

        # 创建 failed 任务
        failed_task = TopicSummaryTaskOrm(
            topic_id=topic.id,
            time_span_hours=24,
            deadline=datetime.now(timezone.utc),
            status=TopicSummaryTaskStatus.failed.value,
            error_message="测试失败",
            completed_at=datetime.now(timezone.utc),
        )
        ls_test_session.add(failed_task)
        await ls_test_session.commit()

        response = await ls_client.get(f"/api/topics/{topic.id}/latest-summary")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "暂无已完成的摘要" in response.json()["detail"]
