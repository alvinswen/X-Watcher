"""Analytics API 集成测试。

使用 async_client fixture（已配置管理员认证和测试数据库）。
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from src.database.models import ScraperFollow
from src.scraper.infrastructure.models import TweetOrm
from src.topic.infrastructure.models import TopicAccountOrm, TopicOrm


async def _seed_analytics_data(session):
    """创建分析测试数据：主题 + 账号 + 推文。"""
    # scraper_follows
    follow = ScraperFollow(
        username="api_user_a", reason="test", added_by="test", is_active=True
    )
    session.add(follow)

    # topic + account
    topic = TopicOrm(name="API测试主题", user_id=0)
    session.add(topic)
    await session.flush()

    acc = TopicAccountOrm(topic_id=topic.id, username="api_user_a")
    session.add(acc)

    # 推文
    now = datetime.now(timezone.utc)
    tweets = [
        TweetOrm(
            tweet_id=f"api_t{i}",
            text=f"API test tweet {i}",
            created_at=now - timedelta(minutes=30 * i + 5),
            db_created_at=now,
            author_username="api_user_a",
            author_display_name="API User A",
            media=None,
        )
        for i in range(3)
    ]
    for t in tweets:
        session.add(t)
    await session.commit()

    return topic.id


@pytest.mark.asyncio
async def test_posting_frequency_success(
    async_client: AsyncClient, async_session
):
    """正常请求应返回 200 和正确的响应结构。"""
    topic_id = await _seed_analytics_data(async_session)

    resp = await async_client.get(
        f"/api/analytics/topics/{topic_id}/posting-frequency",
        params={"tz_offset": 0, "slots": 50},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["topic_id"] == topic_id
    assert data["topic_name"] == "API测试主题"
    assert data["slot_minutes"] == 30
    assert data["slots"] == 50
    assert data["tz_offset"] == 0
    assert "time_range" in data
    assert "start" in data["time_range"]
    assert "end" in data["time_range"]
    assert isinstance(data["distribution"], list)
    assert data["total_tweets"] == 3


@pytest.mark.asyncio
async def test_posting_frequency_topic_not_found(
    async_client: AsyncClient,
):
    """主题不存在应返回 404。"""
    resp = await async_client.get(
        "/api/analytics/topics/99999/posting-frequency",
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_posting_frequency_forbidden(
    async_client: AsyncClient, async_session
):
    """非管理员访问他人主题应返回 403。"""
    # 创建属于 user_id=999 的主题
    topic = TopicOrm(name="他人主题", user_id=999)
    async_session.add(topic)
    await async_session.commit()

    # 模拟非管理员用户
    from src.user.api.auth import get_current_user
    from src.user.domain.models import UserDomain
    from src.main import app

    non_admin_user = UserDomain(
        id=1, name="normal_user", email="user@test.com",
        is_admin=False, created_at=datetime.now(timezone.utc),
    )

    async def override_non_admin():
        return non_admin_user

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = override_non_admin

    try:
        resp = await async_client.get(
            f"/api/analytics/topics/{topic.id}/posting-frequency",
        )
        assert resp.status_code == 403
    finally:
        if original:
            app.dependency_overrides[get_current_user] = original
        else:
            app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_posting_frequency_empty_topic(
    async_client: AsyncClient, async_session
):
    """无关联账号的主题应返回 200 + 空 distribution。"""
    topic = TopicOrm(name="空主题API", user_id=0)
    async_session.add(topic)
    await async_session.commit()

    resp = await async_client.get(
        f"/api/analytics/topics/{topic.id}/posting-frequency",
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["distribution"] == []
    assert data["total_tweets"] == 0


@pytest.mark.asyncio
async def test_posting_frequency_invalid_slots(
    async_client: AsyncClient, async_session
):
    """slots 超范围应返回 422。"""
    topic = TopicOrm(name="参数校验测试", user_id=0)
    async_session.add(topic)
    await async_session.commit()

    # slots > 336
    resp = await async_client.get(
        f"/api/analytics/topics/{topic.id}/posting-frequency",
        params={"slots": 500},
    )
    assert resp.status_code == 422

    # slots < 1
    resp = await async_client.get(
        f"/api/analytics/topics/{topic.id}/posting-frequency",
        params={"slots": 0},
    )
    assert resp.status_code == 422
