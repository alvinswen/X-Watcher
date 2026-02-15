"""用户关注列表 API 集成测试。

测试 PreferenceRouter 端点。
"""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, status

from src.preference.api.routes import preference_router
from src.preference.infrastructure.preference_repository import PreferenceRepository
from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository
from src.database.async_session import get_async_session
from src.database.models import User
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain


class TestPreferenceAPI:
    """测试用户关注列表 API 端点。"""

    @pytest.fixture
    def app(self, async_session):
        """创建测试应用。"""
        app = FastAPI()
        app.include_router(preference_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    async def test_user(self, async_session):
        """创建测试用户。"""
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()
        return user

    @pytest.fixture
    def mock_auth(self, app, test_user):
        """Mock 认证依赖，返回固定用户。"""
        mock_user = UserDomain(
            id=test_user.id,
            name=test_user.name,
            email=test_user.email,
            is_admin=False,
            created_at=test_user.created_at if test_user.created_at else datetime.now(timezone.utc),
        )

        async def override_get_current_user():
            return mock_user

        app.dependency_overrides[get_current_user] = override_get_current_user
        return mock_user

    @pytest.fixture
    async def client(self, app, mock_auth):
        """创建测试客户端（已 mock 认证）。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.fixture
    async def setup_scraper_follows(self, async_session):
        """准备测试用的抓取账号。"""
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("testuser1", "测试账号1", "system")
        await repo.create_scraper_follow("testuser2", "测试账号2", "system")
        await repo.create_scraper_follow("testuser3", "测试账号3", "system")
        await async_session.commit()


class TestFollowManagementAPI(TestPreferenceAPI):
    """测试关注管理 API。"""

    @pytest.mark.asyncio
    async def test_create_follow_success(self, client, test_user, setup_scraper_follows):
        """测试成功创建关注。"""
        request_data = {"username": "testuser1"}

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["username"] == "testuser1"
        assert data["user_id"] == test_user.id
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_follow_invalid_username_format(self, client, test_user):
        """测试无效用户名格式返回 422。"""
        request_data = {"username": "invalid@user!"}

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_create_follow_not_in_scraper_list(self, client, test_user):
        """测试添加不在抓取列表中的账号返回 400。"""
        request_data = {"username": "notinlist"}

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "抓取列表" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_follow_duplicate_returns_409(self, client, test_user, setup_scraper_follows, async_session):
        """测试重复创建关注返回 409。"""
        # 创建第一次关注
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1")
        await async_session.commit()

        # 尝试再次创建
        request_data = {"username": "testuser1"}
        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    async def test_get_follows_success(self, client, test_user, async_session, setup_scraper_follows):
        """测试获取关注列表成功。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1")
        await repo.create_follow(test_user.id, "testuser2")
        await async_session.commit()

        response = await client.get(
            "/api/preferences/follows"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        usernames = {item["username"] for item in data}
        assert "testuser1" in usernames
        assert "testuser2" in usernames

    @pytest.mark.asyncio
    async def test_delete_follow_success(self, client, test_user, async_session, setup_scraper_follows):
        """测试删除关注成功。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1")
        await async_session.commit()

        response = await client.delete(
            "/api/preferences/follows/testuser1"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 验证删除
        follow = await repo.get_follow_by_username(test_user.id, "testuser1")
        assert follow is None

    @pytest.mark.asyncio
    async def test_delete_follow_not_found(self, client, test_user):
        """测试删除不存在的关注返回 404。"""
        response = await client.delete(
            "/api/preferences/follows/nonexistent"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
