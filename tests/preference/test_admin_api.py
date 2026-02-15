"""管理员 API 集成测试。

测试 ScraperConfigRouter 端点，使用 get_current_admin_user 认证。
"""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, status

from src.preference.api.routes import scraper_config_router
from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository
from src.database.async_session import get_async_session
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain


class TestAdminAuth:
    """测试管理员认证。"""

    @pytest.fixture
    def app(self, async_session):
        """创建测试应用（不 mock 管理员认证）。"""
        app = FastAPI()
        app.include_router(scraper_config_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    async def client(self, app):
        """创建测试客户端（未 mock 认证）。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_401(self, client):
        """测试缺少认证凭证返回 401。"""
        response = await client.get("/api/admin/scraping/follows")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_non_admin_user_returns_403(self, app, async_session):
        """测试非管理员用户返回 403。"""
        from fastapi import HTTPException

        async def override_get_current_admin_user():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限",
            )

        app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/admin/scraping/follows",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestScraperConfigAPI:
    """测试抓取配置 API 端点。"""

    @pytest.fixture
    def app(self, async_session):
        """创建测试应用。"""
        app = FastAPI()
        app.include_router(scraper_config_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    def mock_admin(self, app):
        """Mock 管理员认证依赖。"""
        admin_user = UserDomain(
            id=1,
            name="admin",
            email="admin@example.com",
            is_admin=True,
            created_at=datetime.now(timezone.utc),
        )

        async def override_get_current_admin_user():
            return admin_user

        app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user
        return admin_user

    @pytest.fixture
    async def client(self, app, mock_admin):
        """创建测试客户端（已 mock 管理员认证）。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_create_scraper_follow_success(self, client):
        """测试成功创建抓取账号。"""
        request_data = {
            "username": "testuser",
            "reason": "测试账号",
            "added_by": "test_admin"
        }

        response = await client.post(
            "/api/admin/scraping/follows",
            json=request_data,
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["username"] == "testuser"
        assert data["reason"] == "测试账号"
        assert data["added_by"] == "test_admin"
        assert data["is_active"] is True
        assert "id" in data
        assert "added_at" in data

    @pytest.mark.asyncio
    async def test_create_scraper_follow_invalid_username(self, client):
        """测试无效用户名返回 400。"""
        request_data = {
            "username": "invalid@username!",
            "reason": "测试",
            "added_by": "admin"
        }

        response = await client.post(
            "/api/admin/scraping/follows",
            json=request_data,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_create_scraper_follow_duplicate_returns_409(self, client, async_session):
        """测试重复创建返回 409。"""
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow(
            username="duplicate",
            reason="第一次创建",
            added_by="admin"
        )
        await async_session.commit()

        request_data = {
            "username": "duplicate",
            "reason": "第二次创建",
            "added_by": "admin"
        }

        response = await client.post(
            "/api/admin/scraping/follows",
            json=request_data,
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "已存在" in response.json()["detail"] or "conflict" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_scraper_follows_success(self, client, async_session):
        """测试获取抓取列表成功。"""
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("user1", "理由1", "admin1")
        await repo.create_scraper_follow("user2", "理由2", "admin2")
        await async_session.commit()

        response = await client.get(
            "/api/admin/scraping/follows",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 2
        usernames = {item["username"] for item in data}
        assert "user1" in usernames
        assert "user2" in usernames

    @pytest.mark.asyncio
    async def test_get_scraper_follows_include_inactive(self, client, async_session):
        """测试获取包含非活跃账号的列表。"""
        repo = ScraperConfigRepository(async_session)
        follow = await repo.create_scraper_follow("inactive_user", "测试", "admin")
        await repo.deactivate_follow(follow.username)
        await async_session.commit()

        # 只获取活跃账号
        response = await client.get(
            "/api/admin/scraping/follows?include_inactive=false",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert not any(item["username"] == "inactive_user" for item in data)

        # 获取所有账号（包括非活跃）
        response = await client.get(
            "/api/admin/scraping/follows?include_inactive=true",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert any(item["username"] == "inactive_user" for item in data)

    @pytest.mark.asyncio
    async def test_update_scraper_follow_success(self, client, async_session):
        """测试更新抓取账号成功。"""
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("updatable", "原理由", "admin")
        await async_session.commit()

        update_data = {
            "reason": "新理由",
            "is_active": False
        }

        response = await client.put(
            "/api/admin/scraping/follows/updatable",
            json=update_data,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["reason"] == "新理由"
        assert data["is_active"] is False

    @pytest.mark.asyncio
    async def test_update_scraper_follow_not_found(self, client):
        """测试更新不存在的账号返回 404。"""
        update_data = {"reason": "新理由"}

        response = await client.put(
            "/api/admin/scraping/follows/nonexistent",
            json=update_data,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_scraper_follow_success(self, client, async_session):
        """测试软删除抓取账号成功。"""
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("deletable", "测试", "admin")
        await async_session.commit()

        response = await client.delete(
            "/api/admin/scraping/follows/deletable",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 验证软删除（账号仍然存在但 is_active=False）
        follows = await repo.get_all_follows(include_inactive=True)
        deleted_follow = next((f for f in follows if f.username == "deletable"), None)
        assert deleted_follow is not None
        assert deleted_follow.is_active is False

    @pytest.mark.asyncio
    async def test_delete_scraper_follow_not_found(self, client):
        """测试删除不存在的账号返回 404。"""
        response = await client.delete(
            "/api/admin/scraping/follows/nonexistent",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
