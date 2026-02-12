"""调度配置 API 集成测试。

测试 GET/PUT schedule 端点。
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, HTTPException, status

from src.preference.api.scraper_config_router import router as scraper_config_router
from src.database.async_session import get_async_session
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain


class TestScheduleAuth:
    """测试调度配置端点认证。"""

    @pytest.fixture
    def app(self, async_session):
        app = FastAPI()
        app.include_router(scraper_config_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    async def client(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_401(self, client):
        """未认证请求返回 401。"""
        response = await client.get("/api/admin/scraping/schedule")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self, app, async_session):
        """非管理员请求返回 403。"""
        async def override():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限",
            )

        app.dependency_overrides[get_current_admin_user] = override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/admin/scraping/schedule")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestScheduleConfigAPI:
    """测试调度配置 API 端点。"""

    @pytest.fixture
    def app(self, async_session):
        app = FastAPI()
        app.include_router(scraper_config_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    def mock_admin(self, app):
        admin_user = UserDomain(
            id=1,
            name="admin",
            email="admin@example.com",
            is_admin=True,
            created_at=datetime.now(timezone.utc),
        )

        async def override():
            return admin_user

        app.dependency_overrides[get_current_admin_user] = override
        return admin_user

    @pytest.fixture
    async def client(self, app, mock_admin):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_get_schedule_default_config(self, client):
        """GET 返回默认配置。"""
        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            with patch("src.preference.services.schedule_service.get_settings") as mock_settings:
                mock_settings.return_value.scraper_interval = 43200
                response = await client.get("/api/admin/scraping/schedule")

        assert response.status_code == 200
        data = response.json()
        assert data["interval_seconds"] == 43200
        assert data["scheduler_running"] is False

    @pytest.mark.asyncio
    async def test_put_schedule_interval_success(self, client):
        """PUT interval 正常更新。"""
        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            response = await client.put(
                "/api/admin/scraping/schedule/interval",
                json={"interval_seconds": 600},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["interval_seconds"] == 600

    @pytest.mark.asyncio
    async def test_put_schedule_interval_too_small(self, client):
        """PUT interval 值太小返回 422。"""
        response = await client.put(
            "/api/admin/scraping/schedule/interval",
            json={"interval_seconds": 100},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_put_schedule_interval_too_large(self, client):
        """PUT interval 值太大返回 422。"""
        response = await client.put(
            "/api/admin/scraping/schedule/interval",
            json={"interval_seconds": 700000},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_put_schedule_next_run_success(self, client):
        """PUT next-run 正常更新。"""
        future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            response = await client.put(
                "/api/admin/scraping/schedule/next-run",
                json={"next_run_time": future_time},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["next_run_time"] is not None

    @pytest.mark.asyncio
    async def test_put_schedule_next_run_past_time(self, client):
        """PUT next-run 过去时间返回 422。"""
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            response = await client.put(
                "/api/admin/scraping/schedule/next-run",
                json={"next_run_time": past_time},
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_put_schedule_next_run_too_far(self, client):
        """PUT next-run 超过 30 天返回 422。"""
        far_time = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            response = await client.put(
                "/api/admin/scraping/schedule/next-run",
                json={"next_run_time": far_time},
            )

        assert response.status_code == 422
