"""配置验证 API 路由测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from src.api.routes.config_routes import (
    _check_database,
    _check_llm_providers,
    _check_single_provider,
    _check_twitter_api,
)


class TestCheckLLMProviders:
    """测试 _check_llm_providers 内部函数。"""

    @pytest.mark.asyncio
    async def test_config_load_failure(self):
        """测试 LLM 配置加载失败时返回错误状态。"""
        with patch(
            "src.api.routes.config_routes.LLMProviderConfig.from_env",
            side_effect=ValueError("无效的 LLM 配置"),
        ):
            result = await _check_llm_providers()

        assert len(result) == 1
        assert result[0]["name"] == "config_error"
        assert result[0]["status"] == "unhealthy"
        assert "无效的 LLM 配置" in result[0]["error"]

    @pytest.mark.asyncio
    async def test_healthy_provider(self):
        """测试健康的 LLM 提供商。"""
        mock_provider = MagicMock()
        mock_provider.get_provider_name.return_value = "test-provider"
        mock_provider.get_model_name.return_value = "test-model"

        # 模拟 Result 类型的成功响应
        mock_result = MagicMock()
        mock_result.value_or.return_value = "OK"
        mock_provider.complete = AsyncMock(return_value=mock_result)

        with (
            patch(
                "src.api.routes.config_routes.LLMProviderConfig.from_env",
                return_value=MagicMock(),
            ),
            patch(
                "src.api.routes.config_routes._build_providers_from_config",
                return_value=[mock_provider],
            ),
        ):
            result = await _check_llm_providers()

        assert len(result) == 1
        assert result[0]["name"] == "test-provider"
        assert result[0]["status"] == "healthy"
        assert "latency_ms" in result[0]

    @pytest.mark.asyncio
    async def test_empty_providers(self):
        """测试无提供商时返回空列表。"""
        with (
            patch(
                "src.api.routes.config_routes.LLMProviderConfig.from_env",
                return_value=MagicMock(),
            ),
            patch(
                "src.api.routes.config_routes._build_providers_from_config",
                return_value=[],
            ),
        ):
            result = await _check_llm_providers()

        assert result == []


class TestCheckSingleProvider:
    """测试 _check_single_provider 内部函数。"""

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """测试提供商超时返回 unhealthy。"""
        mock_provider = MagicMock()
        mock_provider.get_provider_name.return_value = "slow-provider"
        mock_provider.get_model_name.return_value = "slow-model"
        mock_provider.complete = AsyncMock(side_effect=asyncio.TimeoutError)

        result = await _check_single_provider(mock_provider)

        assert result["status"] == "unhealthy"
        assert "超时" in result["error"]

    @pytest.mark.asyncio
    async def test_result_failure(self):
        """测试 Result.failure 返回 unhealthy。"""
        mock_provider = MagicMock()
        mock_provider.get_provider_name.return_value = "fail-provider"
        mock_provider.get_model_name.return_value = "fail-model"

        mock_result = MagicMock()
        mock_result.value_or.return_value = None
        mock_result.failure.return_value = "API 密钥无效"
        mock_provider.complete = AsyncMock(return_value=mock_result)

        result = await _check_single_provider(mock_provider)

        assert result["status"] == "unhealthy"
        assert result["error"] == "API 密钥无效"

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """测试通用异常返回 unhealthy。"""
        mock_provider = MagicMock()
        mock_provider.get_provider_name.return_value = "error-provider"
        mock_provider.get_model_name.return_value = "error-model"
        mock_provider.complete = AsyncMock(
            side_effect=ConnectionError("无法连接")
        )

        result = await _check_single_provider(mock_provider)

        assert result["status"] == "unhealthy"
        assert "无法连接" in result["error"]


class TestCheckTwitterAPI:
    """测试 _check_twitter_api 内部函数。"""

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        """测试未配置 API Key 返回 unhealthy。"""
        with patch.dict("os.environ", {"TWITTER_API_KEY": ""}, clear=False):
            result = await _check_twitter_api()

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
            patch("src.api.routes.config_routes.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _check_twitter_api()

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
            patch("src.api.routes.config_routes.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _check_twitter_api()

        assert result["status"] == "unhealthy"
        assert "401" in result["error"]

    @pytest.mark.asyncio
    async def test_network_error(self):
        """测试网络异常返回 unhealthy。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=ConnectionError("DNS 解析失败")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(
                "os.environ",
                {"TWITTER_API_KEY": "test-key"},
                clear=False,
            ),
            patch("src.api.routes.config_routes.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _check_twitter_api()

        assert result["status"] == "unhealthy"
        assert "DNS" in result["error"]


class TestCheckDatabase:
    """测试 _check_database 内部函数。"""

    @pytest.mark.asyncio
    async def test_healthy_database(self):
        """测试数据库连接正常时返回 healthy。"""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=None)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_maker = MagicMock(return_value=mock_session)

        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=mock_session_maker,
        ):
            result = await _check_database()

        assert result["status"] == "healthy"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_database_connection_error(self):
        """测试数据库连接失败时返回 unhealthy。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            side_effect=Exception("无法连接数据库"),
        ):
            result = await _check_database()

        assert result["status"] == "unhealthy"
        assert "无法连接数据库" in result["error"]


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
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
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
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/api/admin/config/validate")
            assert resp.status_code == 403
        finally:
            if original:
                app.dependency_overrides[get_current_admin_user] = original
            else:
                app.dependency_overrides.pop(get_current_admin_user, None)
