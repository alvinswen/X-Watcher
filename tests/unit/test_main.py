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
    assert "scheduler" in data["components"]


def test_cors_middleware_configured():
    """测试 CORS 中间件已配置。"""
    from src.main import app

    # 检查 CORS 中间件是否存在
    from fastapi.middleware.cors import CORSMiddleware

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
