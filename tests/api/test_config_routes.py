"""配置验证 API 路由测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from src.shared.connectivity_check import check_twitter_api


class TestCheckTwitterAPI:
    """测试共享 Twitter API 连通性检查。"""

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        """测试未配置 API Key 返回 unhealthy。"""
        with patch.dict("os.environ", {"TWITTER_API_KEY": ""}, clear=False):
            result = await check_twitter_api()

        assert result["status"] == "unhealthy"
        assert "未配置" in result["error"]

    @pytest.mark.asyncio
    async def test_healthy_response(self):
        """测试 API 返回 200 时标记 healthy。"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(
                "os.environ",
                {"TWITTER_API_KEY": "test-key"},
                clear=False,
            ),
            patch(
                "src.shared.connectivity_check.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await check_twitter_api()

        assert result["status"] == "healthy"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_unhealthy_http_error(self):
        """测试非 200 HTTP 状态返回 unhealthy。"""
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(
                "os.environ",
                {"TWITTER_API_KEY": "bad-key"},
                clear=False,
            ),
            patch(
                "src.shared.connectivity_check.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await check_twitter_api()

        assert result["status"] == "unhealthy"
        assert "401" in result["error"]

    @pytest.mark.asyncio
    async def test_network_error(self):
        """测试网络异常返回 unhealthy。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("DNS 解析失败"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(
                "os.environ",
                {"TWITTER_API_KEY": "test-key"},
                clear=False,
            ),
            patch(
                "src.shared.connectivity_check.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await check_twitter_api()

        assert result["status"] == "unhealthy"
        assert "DNS" in result["error"]


class TestValidateConfigEndpointAuth:
    """测试 /api/admin/config/validate 端点的认证要求。"""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self):
        """无认证凭证访问 validate 端点应返回 401。"""
        from httpx import ASGITransport, AsyncClient

        from src.main import app
        from src.user.api.auth import get_current_admin_user

        async def override_deny():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少认证凭证",
            )

        original = app.dependency_overrides.get(get_current_admin_user)
        app.dependency_overrides[get_current_admin_user] = override_deny

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/admin/config/validate")
            assert resp.status_code == 401
        finally:
            if original:
                app.dependency_overrides[get_current_admin_user] = original
            else:
                app.dependency_overrides.pop(get_current_admin_user, None)

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self):
        """非管理员用户访问 validate 端点应返回 403。"""
        from httpx import ASGITransport, AsyncClient

        from src.main import app
        from src.user.api.auth import get_current_admin_user

        async def override_forbidden():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限",
            )

        original = app.dependency_overrides.get(get_current_admin_user)
        app.dependency_overrides[get_current_admin_user] = override_forbidden

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/admin/config/validate")
            assert resp.status_code == 403
        finally:
            if original:
                app.dependency_overrides[get_current_admin_user] = original
            else:
                app.dependency_overrides.pop(get_current_admin_user, None)
