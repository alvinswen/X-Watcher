"""测试 FastAPI 应用。"""

import os

import pytest
from fastapi.testclient import TestClient

from src.config import clear_settings_cache


@pytest.fixture(scope="module")
def client():
    """模块级 TestClient，禁用调度器避免 lifespan 阻塞。"""
    from src.main import app

    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()
    with TestClient(app) as c:
        yield c
    clear_settings_cache()


def test_health_endpoint(client):
    """测试健康检查端点。"""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "components" in data
    assert "database" in data["components"]
    assert "scheduler" not in data["components"]


def test_cors_middleware_configured():
    """测试 CORS 中间件已配置。"""
    # 检查 CORS 中间件是否存在
    from fastapi.middleware.cors import CORSMiddleware

    from src.main import app

    cors_middleware = None
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            cors_middleware = middleware
            break

    assert cors_middleware is not None, "CORS 中间件未配置"


def test_docs_endpoint_available(client):
    """测试 Swagger UI 文档可访问。"""
    response = client.get("/docs")

    assert response.status_code == 200


def test_openapi_schema_available(client):
    """测试 OpenAPI schema 可访问。"""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "openapi" in response.json()


@pytest.mark.asyncio
async def test_lifespan_rejects_weak_jwt_secret(monkeypatch, capsys):
    """测试 REST lifespan 对弱默认 JWT 密钥 fail-loud 拒起。"""
    from src.main import app, lifespan

    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
    monkeypatch.setenv("SCRAPER_ENABLED", "false")
    clear_settings_cache()

    with pytest.raises(SystemExit) as exc_info:
        async with lifespan(app):
            pass

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "JWT 签名密钥强度校验未通过" in stderr
    assert "默认值" in stderr
    assert 'python -c "import secrets;print(secrets.token_urlsafe(32))"' in stderr
    assert "Traceback" not in stderr

    clear_settings_cache()
