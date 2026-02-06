"""测试 FastAPI 应用。"""

import pytest

from fastapi.testclient import TestClient


def test_health_endpoint():
    """测试健康检查端点。"""
    from src.main import app

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


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


def test_docs_endpoint_available():
    """测试 Swagger UI 文档可访问。"""
    from src.main import app

    client = TestClient(app)
    response = client.get("/docs")

    assert response.status_code == 200


def test_openapi_schema_available():
    """测试 OpenAPI schema 可访问。"""
    from src.main import app

    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "openapi" in response.json()
