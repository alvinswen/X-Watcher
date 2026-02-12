"""抓取账号公共只读端点测试。

测试普通用户可以读取抓取账号列表和描述信息，
但不能通过管理员端点进行增、改、删操作。
"""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, HTTPException, status

from src.preference.api.scraper_config_router import public_router, router as admin_router
from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository
from src.database.async_session import get_async_session
from src.user.api.auth import get_current_user, get_current_admin_user
from src.user.domain.models import UserDomain


class TestPublicScraperFollowsAPI:
    """测试公共只读抓取账号端点。"""

    @pytest.fixture
    def app(self, async_session):
        """创建测试应用（同时包含管理员和公共路由）。"""
        app = FastAPI()
        app.include_router(admin_router)
        app.include_router(public_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
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
            created_at=datetime.now(timezone.utc),
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
    async def test_regular_user_can_read_scraper_follows(self, client, async_session):
        """测试普通用户可以读取抓取账号列表。"""
        # Arrange - 先通过 repository 添加测试数据
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("elonmusk", "科技领袖", "admin")
        await repo.create_scraper_follow("openai", "AI 研究机构", "admin")
        await async_session.commit()

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
    async def test_response_contains_reason_field(self, client, async_session):
        """测试响应包含 reason（描述信息）字段。"""
        # Arrange
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("elonmusk", "Tesla/SpaceX CEO", "admin")
        await async_session.commit()

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
    async def test_only_active_follows_returned(self, client, async_session):
        """测试只返回活跃账号（不含已禁用的）。"""
        # Arrange
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("active_user", "活跃账号", "admin")
        await repo.create_scraper_follow("inactive_user", "已禁用账号", "admin")
        await repo.deactivate_follow("inactive_user")
        await async_session.commit()

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
    def app(self, async_session):
        """创建测试应用。"""
        app = FastAPI()
        app.include_router(admin_router)
        app.include_router(public_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override

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
