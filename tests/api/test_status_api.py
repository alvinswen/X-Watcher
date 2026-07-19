"""系统状态概览 API 集成测试。

测试完整调用链：HTTP 请求 → 认证 → 聚合查询 → 响应格式验证。
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from src.config import clear_settings_cache
from src.main import app
from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.user.domain.models import UserDomain


@pytest.fixture(autouse=True)
def file_data_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    clear_settings_cache()
    yield
    clear_settings_cache()


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
    return datetime(2026, 2, 19, 8, 0, 0, tzinfo=UTC)


@pytest.fixture
async def status_client(mock_user, mock_start_time):
    """Status API 集成测试客户端（带认证 + mock start_time）。"""
    from src.user.api.auth import get_current_user

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    with patch(
        "src.api.routes.status.get_server_start_time",
        return_value=mock_start_time,
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def seed_status_data():
    """准备 Status 测试数据。

    - 5 条推文（3 条今日、2 条昨天）
    - 3 条摘要（2 条推文待摘要）
    - 3 个关注账号（2 活跃 + 1 非活跃）
    """
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 今日推文
    tweets = []
    for i in range(3):
        tweet = Tweet(
            tweet_id=f"today_tweet_{i}",
            text=f"Today tweet {i}",
            created_at=today_start + timedelta(hours=i + 1),
            author_username="alice",
            author_display_name="Alice",
            media=None,
        )
        tweets.append(tweet)

    # 昨日推文
    for i in range(2):
        tweet = Tweet(
            tweet_id=f"yesterday_tweet_{i}",
            text=f"Yesterday tweet {i}",
            created_at=today_start - timedelta(hours=i + 1),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        )
        tweets.append(tweet)

    root = Path(os.environ["XWATCHER_DATA_ROOT"])
    await FileTweetStore(root).save_tweets(tweets, early_stop_threshold=0)

    # 摘要（覆盖 3 条推文，2 条无摘要）
    summaries = []
    for i in range(3):
        summary = SummaryRecord(
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
            created_at=now,
            updated_at=now,
        )
        summaries.append(summary)
    await FileSummaryStore(root).seed(summaries)

    # 关注账号
    await FileFollowStore(root).seed(
        [
            ScraperFollow(
                id=1,
                username="alice",
                added_at=now,
                reason="test",
                added_by="admin",
                is_active=True,
            ),
            ScraperFollow(
                id=2,
                username="bob",
                added_at=now + timedelta(seconds=1),
                reason="test",
                added_by="admin",
                is_active=True,
            ),
            ScraperFollow(
                id=3,
                username="charlie",
                added_at=now + timedelta(seconds=2),
                reason="test",
                added_by="admin",
                is_active=False,
            ),
        ]
    )


class TestStatusOverviewSuccess:
    """测试成功场景。"""

    async def test_full_response_structure(self, status_client: AsyncClient, seed_status_data):
        """完整调用链成功：200 + 在线状态字段存在。"""
        response = await status_client.get("/api/status/overview")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # 验证已保留的顶级字段
        assert "tweets" in data
        assert "follows" in data
        assert "summaries" in data
        assert "system" in data
        assert "topics" not in data
        assert "scheduler" not in data

    async def test_tweet_stats(self, status_client: AsyncClient, seed_status_data):
        """推文统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        tweets = data["tweets"]
        assert tweets["total"] == 5
        assert tweets["today_count"] == 3
        assert tweets["latest_tweet_at"] is not None

    async def test_follow_stats(self, status_client: AsyncClient, seed_status_data):
        """关注统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        follows = data["follows"]
        assert follows["total"] == 3
        assert follows["active"] == 2
        assert follows["inactive"] == 1

    async def test_summary_stats(self, status_client: AsyncClient, seed_status_data):
        """摘要统计数值正确。"""
        response = await status_client.get("/api/status/overview")
        data = response.json()

        summaries = data["summaries"]
        assert summaries["total"] == 3
        # 5 条推文 - 3 条有摘要 = 2 条待摘要
        assert summaries["pending_tweets"] == 2

    async def test_system_stats(self, status_client: AsyncClient, seed_status_data):
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
        assert "topics" not in data
        assert "scheduler" not in data
