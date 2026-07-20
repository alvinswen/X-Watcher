"""登录 API (POST /api/auth/login) 测试。"""

import os
from pathlib import Path

import pytest

from src.config import clear_settings_cache
from src.user.infrastructure.file_user_repository import FileUserStore
from src.user.services.auth_service import AuthService

JWT_SECRET = "test-auth-api-jwt-secret-key-32bytes!"


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """设置测试环境变量。"""
    originals = {
        "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY"),
        "XWATCHER_DATA_ROOT": os.environ.get("XWATCHER_DATA_ROOT"),
    }
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    os.environ["XWATCHER_DATA_ROOT"] = str(tmp_path)
    clear_settings_cache()
    yield
    for key, value in originals.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    clear_settings_cache()


@pytest.fixture
async def seeded_client(client_and_session):
    """创建测试用户并返回 (client, user_email, user_password)。"""
    client, _ = client_and_session
    auth_svc = AuthService()

    password = "TestPassword123"
    pw_hash = await auth_svc.hash_password(password)
    store = FileUserStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
    await store.create_user(
        name="testuser",
        email="test@example.com",
        password_hash=pw_hash,
    )

    return client, "test@example.com", password


@pytest.mark.asyncio
async def test_login_success(seeded_client):
    """正确凭证登录返回 JWT。"""
    client, email, password = seeded_client

    resp = await client.post("/api/auth/login", json={"email": email, "password": password})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.asyncio
async def test_login_wrong_password(seeded_client):
    """错误密码返回 401。"""
    client, email, _ = seeded_client

    resp = await client.post("/api/auth/login", json={"email": email, "password": "WrongPass999"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(seeded_client):
    """不存在的邮箱返回 401。"""
    client, _, password = seeded_client

    resp = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": password})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_jwt_works_for_me_endpoint(seeded_client):
    """登录返回的 JWT 可用于 GET /api/users/me 认证。"""
    client, email, password = seeded_client

    # 先登录获取 JWT
    login_resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # 用 JWT 访问 /me
    me_resp = await client.get(
        "/api/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == email
    assert me_data["name"] == "testuser"
    assert me_data["is_admin"] is False
