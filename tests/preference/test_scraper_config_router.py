"""抓取账号公共只读端点测试。

测试普通用户可以读取抓取账号列表和描述信息，
但不能通过管理员端点进行增、改、删操作。
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from src.preference.api.scraper_config_router import public_router
from src.preference.api.scraper_config_router import router as admin_router
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.user.api.auth import get_current_admin_user, get_current_user
from src.user.domain.models import UserDomain


@pytest.fixture(autouse=True)
def file_data_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))


class TestPublicScraperFollowsAPI:
    """测试公共只读抓取账号端点。"""

    @pytest.fixture
    def app(self):
        """创建测试应用（同时包含管理员和公共路由）。"""
        app = FastAPI()
        app.include_router(admin_router)
        app.include_router(public_router)

        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    def mock_user(self, app):
        """Mock 普通用户认证依赖。"""
        user = UserDomain(
            id=10,
            name="regular_user",
            email="user@example.com",
            is_admin=False,
            created_at=datetime.now(UTC),
        )

        async def override_get_current_user():
            return user

        app.dependency_overrides[get_current_user] = override_get_current_user
        return user

    @pytest.fixture
    async def client(self, app, mock_user):
        """创建测试客户端（已 mock 普通用户认证）。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.fixture
    async def client_no_auth(self, app):
        """创建无认证的测试客户端。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_regular_user_can_read_scraper_follows(self, client):
        """测试普通用户可以读取抓取账号列表。"""
        # Arrange - 先通过 repository 添加测试数据
        repo = FileFollowStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
        await repo.create_scraper_follow("elonmusk", "科技领袖", "admin")
        await repo.create_scraper_follow("openai", "AI 研究机构", "admin")

        # Act
        response = await client.get("/api/scraping/follows")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        usernames = {item["username"] for item in data}
        assert "elonmusk" in usernames
        assert "openai" in usernames

    @pytest.mark.asyncio
    async def test_response_contains_reason_field(self, client):
        """测试响应包含 reason（描述信息）字段。"""
        # Arrange
        repo = FileFollowStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
        await repo.create_scraper_follow("elonmusk", "Tesla/SpaceX CEO", "admin")

        # Act
        response = await client.get("/api/scraping/follows")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["reason"] == "Tesla/SpaceX CEO"
        assert data[0]["username"] == "elonmusk"
        assert data[0]["is_active"] is True
        assert "added_by" in data[0]
        assert "added_at" in data[0]

    @pytest.mark.asyncio
    async def test_only_active_follows_returned(self, client):
        """测试只返回活跃账号（不含已禁用的）。"""
        # Arrange
        repo = FileFollowStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
        await repo.create_scraper_follow("active_user", "活跃账号", "admin")
        await repo.create_scraper_follow("inactive_user", "已禁用账号", "admin")
        await repo.deactivate_follow("inactive_user")

        # Act
        response = await client.get("/api/scraping/follows")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["username"] == "active_user"

    @pytest.mark.asyncio
    async def test_empty_list_when_no_follows(self, client):
        """测试没有抓取账号时返回空列表。"""
        response = await client.get("/api/scraping/follows")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, client_no_auth):
        """测试未认证请求返回 401。"""
        response = await client_no_auth.get("/api/scraping/follows")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRegularUserCannotAccessAdminEndpoints:
    """测试普通用户不能访问管理员端点（增/改/删）。"""

    @pytest.fixture
    def app(self):
        """创建测试应用。"""
        app = FastAPI()
        app.include_router(admin_router)
        app.include_router(public_router)

        # Mock 管理员认证依赖 -> 403
        async def override_get_current_admin_user():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限",
            )

        app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user

        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    async def client(self, app):
        """创建测试客户端（模拟普通用户被拒绝管理员权限）。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_regular_user_cannot_create_follow(self, client):
        """测试普通用户不能添加抓取账号。"""
        response = await client.post(
            "/api/admin/scraping/follows",
            json={"username": "test", "reason": "测试", "added_by": "user"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_regular_user_cannot_update_follow(self, client):
        """测试普通用户不能更新抓取账号。"""
        response = await client.put(
            "/api/admin/scraping/follows/testuser",
            json={"reason": "新理由"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_regular_user_cannot_delete_follow(self, client):
        """测试普通用户不能删除抓取账号。"""
        response = await client.delete(
            "/api/admin/scraping/follows/testuser",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
class TestCHG032ProfileAndTimeRange:
    """CHG-032 TC-BUILD-406/412/419。"""

    async def test_tc_build_406_fetch_failure_still_exits_client_context(self):
        from src.preference.api.scraper_config_router import sync_user_profiles

        repo = Mock()
        repo.get_all_follows = AsyncMock(return_value=[Mock(platform_user_id="uid-1")])
        client = Mock()
        client.fetch_user_info_by_ids = AsyncMock(side_effect=RuntimeError("fetch failed"))
        manager = Mock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.preference.api.scraper_config_router.get_follows_repo", return_value=repo),
            patch("src.scraper.client.TwitterClient", return_value=manager),
            pytest.raises(HTTPException) as exc_info,
        ):
            await sync_user_profiles(admin=Mock())

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        manager.__aexit__.assert_awaited_once()

    async def test_tc_build_412_rest_time_range_delegates_without_value_drift(self):
        from src.preference.api.scraper_config_router import get_follows_tweet_time_range

        earliest = datetime(2026, 7, 1, tzinfo=UTC)
        latest = datetime(2026, 7, 2, tzinfo=UTC)
        service = Mock()
        service.get_all_follows = AsyncMock(return_value=[Mock(username="Alice")])
        shared = AsyncMock(return_value={"Alice": (earliest, latest, 3)})
        with (
            patch(
                "src.preference.api.scraper_config_router._get_scraper_config_service",
                new=AsyncMock(return_value=service),
            ),
            patch(
                "src.preference.services.scraper_config_service.get_tweet_time_ranges",
                new=shared,
            ),
        ):
            result = await get_follows_tweet_time_range(admin=Mock())

        shared.assert_awaited_once_with(["Alice"])
        assert result[0].model_dump() == {
            "username": "Alice",
            "earliest_tweet_at": earliest,
            "latest_tweet_at": latest,
            "tweet_count": 3,
        }

    async def test_tc_build_419_sync_normal_empty_result_is_unchanged(self):
        from returns.result import Success

        from src.preference.api.scraper_config_router import sync_user_profiles

        repo = Mock()
        repo.get_all_follows = AsyncMock(return_value=[Mock(platform_user_id="uid-1")])
        client = Mock()
        client.fetch_user_info_by_ids = AsyncMock(return_value=Success([]))
        manager = Mock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=None)
        with (
            patch("src.preference.api.scraper_config_router.get_follows_repo", return_value=repo),
            patch("src.scraper.client.TwitterClient", return_value=manager),
        ):
            result = await sync_user_profiles(admin=Mock())

        assert result.synced == 0
        assert result.message == "API 返回空结果"
        manager.__aexit__.assert_awaited_once()
