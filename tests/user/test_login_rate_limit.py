"""登录限流与 ADMIN_API_KEY 常量时间比较回归（CHG-041）。"""

import os
from pathlib import Path

import pytest
from fastapi import HTTPException, status

from src.config import clear_settings_cache
from src.user.domain.models import BOOTSTRAP_ADMIN
from src.user.infrastructure.file_user_repository import FileUserStore
from src.user.services.auth_service import AuthService
from src.user.services.login_rate_limiter import login_rate_limiter

JWT_SECRET = "test-login-rate-limit-jwt-secret-32bytes"
ADMIN_API_KEY = "test-admin-api-key-constant-time"


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """为登录与认证测试提供独立数据根和确定配置。"""
    originals = {
        "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY"),
        "ADMIN_API_KEY": os.environ.get("ADMIN_API_KEY"),
        "XWATCHER_DATA_ROOT": os.environ.get("XWATCHER_DATA_ROOT"),
    }
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    os.environ["ADMIN_API_KEY"] = ADMIN_API_KEY
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
async def two_users(client_and_session):
    """创建两个可登录用户并返回 client 与凭据。"""
    client, _ = client_and_session
    auth = AuthService()
    store = FileUserStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
    password_a = "PasswordA123"
    password_b = "PasswordB123"
    await store.create_user(
        "user-a",
        "a@example.com",
        await auth.hash_password(password_a),
    )
    await store.create_user(
        "user-b",
        "b@example.com",
        await auth.hash_password(password_b),
    )
    return client, password_a, password_b


@pytest.mark.asyncio
async def test_five_failures_lock_until_window_expires(two_users):
    """第 5 次失败触发锁定，第 6 次起 429，到点自动恢复。"""
    client, password_a, _ = two_users
    fake_now = [0.0]
    login_rate_limiter.clock = lambda: fake_now[0]

    for _ in range(5):
        response = await client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "wrong"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    locked = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "wrong"},
    )
    assert locked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert locked.json() == {"detail": "登录尝试过于频繁，请约 15 分钟后重试"}
    assert locked.headers["Retry-After"] == "900"

    correct_while_locked = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": password_a},
    )
    assert correct_while_locked.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    fake_now[0] = 899.9
    still_locked = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": password_a},
    )
    assert still_locked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert still_locked.headers["Retry-After"] == "1"

    fake_now[0] = 900.1
    recovered = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": password_a},
    )
    assert recovered.status_code == status.HTTP_200_OK

    first_failure_after_recovery = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "wrong"},
    )
    assert first_failure_after_recovery.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_success_breaks_consecutive_failure_chain(two_users):
    """成功登录清零，使后续失败从 1 重新计数。"""
    client, password_a, _ = two_users
    login_rate_limiter.clock = lambda: 0.0

    for _ in range(4):
        response = await client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "wrong"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    success = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": password_a},
    )
    assert success.status_code == status.HTTP_200_OK

    next_failure = await client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "wrong"},
    )
    assert next_failure.status_code == status.HTTP_401_UNAUTHORIZED
    assert login_rate_limiter._failure_count == 1


@pytest.mark.asyncio
async def test_lock_is_global_and_reset_restores_access(two_users):
    """账号 A 触发的全实例单闸同样拒绝账号 B，reset 模拟重启清零。"""
    client, _, password_b = two_users
    login_rate_limiter.clock = lambda: 0.0

    for _ in range(5):
        response = await client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "wrong"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    other_account = await client.post(
        "/api/auth/login",
        json={"email": "b@example.com", "password": password_b},
    )
    assert other_account.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    login_rate_limiter.reset()
    restored = await client.post(
        "/api/auth/login",
        json={"email": "b@example.com", "password": password_b},
    )
    assert restored.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_rest_admin_api_key_correct_wrong_and_non_ascii():
    """REST ADMIN_API_KEY 三态保持放行/401/401，非 ASCII 不抛 500。"""
    from src.user.api.auth import get_current_user

    assert await get_current_user(api_key=ADMIN_API_KEY, bearer=None) == BOOTSTRAP_ADMIN

    for candidate in ("wrong-admin-key", "sná_密钥"):
        with pytest.raises(HTTPException) as caught:
            await get_current_user(api_key=candidate, bearer=None)
        assert caught.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_admin_fallback_compare_correct_wrong_and_non_ascii(monkeypatch):
    """管理员依赖的 401 fallback 分支也使用 bytes 常量时间比较。"""
    from src.user.api import auth as auth_module

    async def reject_standard_auth(**_kwargs):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
        )

    monkeypatch.setattr(auth_module, "get_current_user", reject_standard_auth)

    assert (
        await auth_module.get_current_admin_user(
            api_key=ADMIN_API_KEY,
            bearer=None,
        )
        == BOOTSTRAP_ADMIN
    )

    for candidate in ("wrong-admin-key", "sná_密钥"):
        with pytest.raises(HTTPException) as caught:
            await auth_module.get_current_admin_user(
                api_key=candidate,
                bearer=None,
            )
        assert caught.value.status_code == status.HTTP_401_UNAUTHORIZED
