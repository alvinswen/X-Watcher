"""Prometheus 监控路由测试。"""

from unittest.mock import MagicMock, patch

import pytest

from src.main import app
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN


@pytest.fixture(autouse=True)
def override_auth():
    """覆盖管理员认证依赖。"""
    app.dependency_overrides[get_current_admin_user] = lambda: BOOTSTRAP_ADMIN
    yield
    app.dependency_overrides.pop(get_current_admin_user, None)


class TestMetricsEndpoint:
    """测试 GET /metrics 端点。"""

    def test_metrics_returns_prometheus_format(self, client):
        """测试返回 Prometheus 文本格式。"""
        response = client.get("/metrics")

        assert response.status_code == 200
        # Prometheus 文本格式的 content type
        assert "text/plain" in response.headers.get("content-type", "")

    def test_metrics_contains_standard_metrics(self, client):
        """测试包含标准 Prometheus 指标。"""
        response = client.get("/metrics")

        assert response.status_code == 200
        content = response.text
        # prometheus_client 默认会包含 python_ 进程指标
        assert "python_info" in content or "process_" in content or "http_" in content

    def test_metrics_disabled(self, client):
        """测试监控禁用时返回提示信息。"""
        mock_settings = MagicMock()
        mock_settings.prometheus_enabled = False

        with patch("src.monitoring.routes.get_settings", return_value=mock_settings):
            response = client.get("/metrics")

        assert response.status_code == 200
        assert b"Monitoring is disabled" in response.content

    def test_metrics_enabled_by_default(self, client):
        """测试默认启用监控（settings 无 prometheus_enabled 属性时）。"""
        mock_settings = MagicMock(spec=[])  # 无 prometheus_enabled 属性

        with patch("src.monitoring.routes.get_settings", return_value=mock_settings):
            response = client.get("/metrics")

        assert response.status_code == 200
        # 不应返回 disabled 消息
        assert b"Monitoring is disabled" not in response.content
