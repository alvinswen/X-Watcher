"""用户操作 API 测试。"""

import os
from pathlib import Path

import pytest

from src.config import clear_settings_cache
from src.user.infrastructure.file_user_repository import FileUserStore
from src.user.services.auth_service import AuthService

JWT_SECRET = "test-user-api-jwt-secret-key-32bytes!"


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """设置测试环境变量。"""
    originals = {
        "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY"),
        "XWATCHER_DATA_LAYER": os.environ.get("XWATCHER_DATA_LAYER"),
        "XWATCHER_DATA_ROOT": os.environ.get("XWATCHER_DATA_ROOT"),
    }
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    os.environ["XWATCHER_DATA_LAYER"] = "file"
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
async def authed_client(client_and_session):
    """创建测试用户并用 JWT 认证的客户端。返回 (client, user, password)。"""
    client, _ = client_and_session
    auth_svc = AuthService()

    password = "TestPassword123"
    pw_hash = await auth_svc.hash_password(password)
    store = FileUserStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
    user = await store.create_user(
        name="testuser",
        email="test@example.com",
        password_hash=pw_hash,
    )

    # 登录获取 JWT
    login_resp = await client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": password},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # 让 client 默认带 Authorization 头
    client.headers["Authorization"] = f"Bearer {token}"

    return client, user, password


@pytest.mark.asyncio
async def test_get_me(authed_client):
    """GET /api/users/me 返回当前用户信息。"""
    client, user, _ = authed_client

    resp = await client.get("/api/users/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["name"] == "testuser"
    assert data["is_admin"] is False


@pytest.mark.asyncio
async def test_create_api_key(authed_client):
    """POST /api/users/me/api-keys 创建成功。"""
    client, _, _ = authed_client

    resp = await client.post(
        "/api/users/me/api-keys",
        json={"name": "my-key"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("sna_")
    assert data["name"] == "my-key"
    assert "key_prefix" in data


@pytest.mark.asyncio
async def test_list_api_keys(authed_client):
    """GET /api/users/me/api-keys 列出 Key。"""
    client, _, _ = authed_client

    # 先创建一个 Key
    await client.post("/api/users/me/api-keys", json={"name": "test-key"})

    resp = await client.get("/api/users/me/api-keys")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["name"] == "test-key"


@pytest.mark.asyncio
async def test_revoke_api_key(authed_client):
    """DELETE /api/users/me/api-keys/{id} 撤销成功。"""
    client, _, _ = authed_client

    # 创建 Key
    create_resp = await client.post("/api/users/me/api-keys", json={"name": "to-revoke"})
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    # 撤销
    resp = await client.delete(f"/api/users/me/api-keys/{key_id}")
    assert resp.status_code == 204

    # 验证列表中已去活
    list_resp = await client.get("/api/users/me/api-keys")
    keys = list_resp.json()
    revoked = [k for k in keys if k["id"] == key_id]
    if revoked:
        assert revoked[0]["is_active"] is False


@pytest.mark.asyncio
async def test_revoke_nonexistent_key(authed_client):
    """撤销不存在的 Key 返回 404。"""
    client, _, _ = authed_client

    resp = await client.delete("/api/users/me/api-keys/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_change_password(authed_client):
    """PUT /api/users/me/password 修改密码成功。"""
    client, _, password = authed_client

    resp = await client.put(
        "/api/users/me/password",
        json={"old_password": password, "new_password": "NewPassword456"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old(authed_client):
    """旧密码错误返回 400。"""
    client, _, _ = authed_client

    resp = await client.put(
        "/api/users/me/password",
        json={"old_password": "WrongOldPass", "new_password": "NewPassword456"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_unauthenticated(client_and_session):
    """无认证凭证返回 401。"""
    client, _ = client_and_session

    resp = await client.get("/api/users/me")
    assert resp.status_code == 401
