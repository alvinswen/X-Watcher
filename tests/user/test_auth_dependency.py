"""认证依赖 get_current_user / get_current_admin_user 测试。"""

import os
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest

from src.config import clear_settings_cache
from src.user.api.auth import get_current_admin_user, get_current_user
from src.user.domain.models import BOOTSTRAP_ADMIN
from src.user.infrastructure.file_user_repository import FileUserStore
from src.user.services.auth_service import AuthService


JWT_SECRET = "test-auth-dep-jwt-secret"
ADMIN_API_KEY_VALUE = "test-admin-api-key-12345"


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """设置测试环境变量。"""
    originals = {
        "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY"),
        "ADMIN_API_KEY": os.environ.get("ADMIN_API_KEY"),
        "XWATCHER_DATA_LAYER": os.environ.get("XWATCHER_DATA_LAYER"),
        "XWATCHER_DATA_ROOT": os.environ.get("XWATCHER_DATA_ROOT"),
    }
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    os.environ["ADMIN_API_KEY"] = ADMIN_API_KEY_VALUE
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
def auth_svc():
    return AuthService()


@pytest.fixture
async def normal_user_with_key(auth_svc):
    """创建普通用户和对应的 API Key，返回 (user, raw_key)。"""
    pw_hash = await auth_svc.hash_password("password123")
    store = FileUserStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
    user = await store.create_user("alice", "alice@test.com", pw_hash)

    raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
    await store.create_api_key(user.id, key_hash, key_prefix, name="default")

    return user, raw_key


@pytest.fixture
async def admin_user_with_key(auth_svc):
    """创建管理员用户和对应的 API Key，返回 (user, raw_key)。"""
    pw_hash = await auth_svc.hash_password("adminpass123")
    store = FileUserStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
    user = await store.create_user("admin", "admin@test.com", pw_hash)
    user = await store.update_user(user.id, is_admin=True)

    raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
    await store.create_api_key(user.id, key_hash, key_prefix, name="admin-key")

    return user, raw_key


@pytest.fixture
async def inactive_key_user(auth_svc):
    """创建用户和一个非活跃的 API Key，返回 (user, raw_key)。"""
    pw_hash = await auth_svc.hash_password("password123")
    store = FileUserStore(Path(os.environ["XWATCHER_DATA_ROOT"]))
    user = await store.create_user("bob", "bob@test.com", pw_hash)

    raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
    api_key = await store.create_api_key(
        user.id, key_hash, key_prefix, name="inactive"
    )
    await store.deactivate_key(api_key.id)

    return user, raw_key


def _make_bearer(credentials: str):
    """构造 HTTPAuthorizationCredentials 模拟对象。"""
    mock = MagicMock()
    mock.credentials = credentials
    return mock


# ---------- get_current_user 测试 ----------

@pytest.mark.asyncio
async def test_api_key_auth_success(normal_user_with_key):
    """API Key 认证成功。"""
    user_orm, raw_key = normal_user_with_key
    result = await get_current_user(api_key=raw_key, bearer=None)
    assert result.id == user_orm.id
    assert result.email == "alice@test.com"


@pytest.mark.asyncio
async def test_api_key_auth_invalid(normal_user_with_key):
    """无效 API Key 返回 401。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key="sna_invalid_key_here", bearer=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_auth_inactive(inactive_key_user):
    """非活跃 Key 返回 401。"""
    from fastapi import HTTPException
    _, raw_key = inactive_key_user
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=raw_key, bearer=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_auth_success(normal_user_with_key, auth_svc):
    """JWT 认证成功。"""
    user_orm, _ = normal_user_with_key
    token = auth_svc.create_jwt_token(
        user_id=user_orm.id, email=user_orm.email, is_admin=user_orm.is_admin
    )
    bearer = _make_bearer(token)
    result = await get_current_user(api_key=None, bearer=bearer)
    assert result.id == user_orm.id
    assert result.email == "alice@test.com"


@pytest.mark.asyncio
async def test_jwt_auth_expired(normal_user_with_key):
    """过期 Token 返回 401。"""
    from fastapi import HTTPException
    user_orm, _ = normal_user_with_key
    expired_payload = {
        "sub": str(user_orm.id),
        "email": user_orm.email,
        "is_admin": False,
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    expired_token = pyjwt.encode(expired_payload, JWT_SECRET, algorithm="HS256")
    bearer = _make_bearer(expired_token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=None, bearer=bearer)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_auth_invalid():
    """无效 Token 返回 401。"""
    from fastapi import HTTPException
    bearer = _make_bearer("this.is.not.a.valid.jwt")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=None, bearer=bearer)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_priority_over_jwt(normal_user_with_key, admin_user_with_key, auth_svc):
    """同时提供 API Key 和 JWT 时，API Key 优先。"""
    normal_user, normal_key = normal_user_with_key
    admin_user, _ = admin_user_with_key

    # JWT 对应 admin 用户，API Key 对应 normal 用户
    admin_token = auth_svc.create_jwt_token(
        user_id=admin_user.id, email=admin_user.email, is_admin=True
    )
    bearer = _make_bearer(admin_token)

    result = await get_current_user(api_key=normal_key, bearer=bearer)
    # 应该返回 API Key 对应的普通用户，而非 JWT 对应的管理员
    assert result.id == normal_user.id
    assert result.email == "alice@test.com"


@pytest.mark.asyncio
async def test_no_credentials_401():
    """无凭证返回 401。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=None, bearer=None)
    assert exc_info.value.status_code == 401


# ---------- get_current_admin_user 测试 ----------

@pytest.mark.asyncio
async def test_admin_user_success(admin_user_with_key):
    """管理员用户认证成功。"""
    admin_user, raw_key = admin_user_with_key
    result = await get_current_admin_user(api_key=raw_key, bearer=None)
    assert result.id == admin_user.id
    assert result.is_admin is True


@pytest.mark.asyncio
async def test_non_admin_user_403(normal_user_with_key):
    """非管理员用户返回 403。"""
    from fastapi import HTTPException
    _, raw_key = normal_user_with_key
    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin_user(api_key=raw_key, bearer=None)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_api_key_bootstrap():
    """ADMIN_API_KEY 返回 BOOTSTRAP_ADMIN。"""
    result = await get_current_admin_user(
        api_key=ADMIN_API_KEY_VALUE, bearer=None
    )
    assert result.id == BOOTSTRAP_ADMIN.id
    assert result.name == "bootstrap"
    assert result.is_admin is True


@pytest.mark.asyncio
async def test_admin_api_key_for_current_user():
    """ADMIN_API_KEY 可用于 get_current_user，返回 BOOTSTRAP_ADMIN。"""
    result = await get_current_user(
        api_key=ADMIN_API_KEY_VALUE, bearer=None
    )
    assert result.id == BOOTSTRAP_ADMIN.id
    assert result.is_admin is True
