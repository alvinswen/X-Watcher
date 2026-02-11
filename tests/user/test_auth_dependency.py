"""认证依赖 get_current_user / get_current_admin_user 测试。"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest

from src.config import clear_settings_cache
from src.database.models import User as UserOrm, ApiKey as ApiKeyOrm
from src.user.api.auth import get_current_user, get_current_admin_user
from src.user.domain.models import BOOTSTRAP_ADMIN
from src.user.services.auth_service import AuthService


JWT_SECRET = "test-auth-dep-jwt-secret"
ADMIN_API_KEY_VALUE = "test-admin-api-key-12345"


@pytest.fixture(autouse=True)
def setup_env():
    """设置测试环境变量。"""
    original_jwt = os.environ.get("JWT_SECRET_KEY")
    original_admin = os.environ.get("ADMIN_API_KEY")
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    os.environ["ADMIN_API_KEY"] = ADMIN_API_KEY_VALUE
    clear_settings_cache()
    yield
    if original_jwt is None:
        os.environ.pop("JWT_SECRET_KEY", None)
    else:
        os.environ["JWT_SECRET_KEY"] = original_jwt
    if original_admin is None:
        os.environ.pop("ADMIN_API_KEY", None)
    else:
        os.environ["ADMIN_API_KEY"] = original_admin
    clear_settings_cache()


@pytest.fixture
def auth_svc():
    return AuthService()


@pytest.fixture
async def normal_user_with_key(async_session, auth_svc):
    """创建普通用户和对应的 API Key，返回 (user_orm, raw_key)。"""
    pw_hash = await auth_svc.hash_password("password123")
    user = UserOrm(name="alice", email="alice@test.com", password_hash=pw_hash, is_admin=False)
    async_session.add(user)
    await async_session.flush()

    raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
    api_key = ApiKeyOrm(
        user_id=user.id, key_hash=key_hash, key_prefix=key_prefix, name="default"
    )
    async_session.add(api_key)
    await async_session.flush()

    return user, raw_key


@pytest.fixture
async def admin_user_with_key(async_session, auth_svc):
    """创建管理员用户和对应的 API Key，返回 (user_orm, raw_key)。"""
    pw_hash = await auth_svc.hash_password("adminpass123")
    user = UserOrm(name="admin", email="admin@test.com", password_hash=pw_hash, is_admin=True)
    async_session.add(user)
    await async_session.flush()

    raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
    api_key = ApiKeyOrm(
        user_id=user.id, key_hash=key_hash, key_prefix=key_prefix, name="admin-key"
    )
    async_session.add(api_key)
    await async_session.flush()

    return user, raw_key


@pytest.fixture
async def inactive_key_user(async_session, auth_svc):
    """创建用户和一个非活跃的 API Key，返回 (user_orm, raw_key)。"""
    pw_hash = await auth_svc.hash_password("password123")
    user = UserOrm(name="bob", email="bob@test.com", password_hash=pw_hash, is_admin=False)
    async_session.add(user)
    await async_session.flush()

    raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
    api_key = ApiKeyOrm(
        user_id=user.id, key_hash=key_hash, key_prefix=key_prefix,
        name="inactive", is_active=False,
    )
    async_session.add(api_key)
    await async_session.flush()

    return user, raw_key


def _make_bearer(credentials: str):
    """构造 HTTPAuthorizationCredentials 模拟对象。"""
    mock = MagicMock()
    mock.credentials = credentials
    return mock


# ---------- get_current_user 测试 ----------

@pytest.mark.asyncio
async def test_api_key_auth_success(async_session, normal_user_with_key):
    """API Key 认证成功。"""
    user_orm, raw_key = normal_user_with_key
    result = await get_current_user(api_key=raw_key, bearer=None, session=async_session)
    assert result.id == user_orm.id
    assert result.email == "alice@test.com"


@pytest.mark.asyncio
async def test_api_key_auth_invalid(async_session, normal_user_with_key):
    """无效 API Key 返回 401。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key="sna_invalid_key_here", bearer=None, session=async_session)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_auth_inactive(async_session, inactive_key_user):
    """非活跃 Key 返回 401。"""
    from fastapi import HTTPException
    _, raw_key = inactive_key_user
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=raw_key, bearer=None, session=async_session)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_auth_success(async_session, normal_user_with_key, auth_svc):
    """JWT 认证成功。"""
    user_orm, _ = normal_user_with_key
    token = auth_svc.create_jwt_token(
        user_id=user_orm.id, email=user_orm.email, is_admin=user_orm.is_admin
    )
    bearer = _make_bearer(token)
    result = await get_current_user(api_key=None, bearer=bearer, session=async_session)
    assert result.id == user_orm.id
    assert result.email == "alice@test.com"


@pytest.mark.asyncio
async def test_jwt_auth_expired(async_session, normal_user_with_key):
    """过期 Token 返回 401。"""
    from fastapi import HTTPException
    user_orm, _ = normal_user_with_key
    expired_payload = {
        "sub": str(user_orm.id),
        "email": user_orm.email,
        "is_admin": False,
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
    }
    expired_token = pyjwt.encode(expired_payload, JWT_SECRET, algorithm="HS256")
    bearer = _make_bearer(expired_token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=None, bearer=bearer, session=async_session)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_auth_invalid(async_session):
    """无效 Token 返回 401。"""
    from fastapi import HTTPException
    bearer = _make_bearer("this.is.not.a.valid.jwt")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=None, bearer=bearer, session=async_session)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_api_key_priority_over_jwt(async_session, normal_user_with_key, admin_user_with_key, auth_svc):
    """同时提供 API Key 和 JWT 时，API Key 优先。"""
    normal_user, normal_key = normal_user_with_key
    admin_user, _ = admin_user_with_key

    # JWT 对应 admin 用户，API Key 对应 normal 用户
    admin_token = auth_svc.create_jwt_token(
        user_id=admin_user.id, email=admin_user.email, is_admin=True
    )
    bearer = _make_bearer(admin_token)

    result = await get_current_user(api_key=normal_key, bearer=bearer, session=async_session)
    # 应该返回 API Key 对应的普通用户，而非 JWT 对应的管理员
    assert result.id == normal_user.id
    assert result.email == "alice@test.com"


@pytest.mark.asyncio
async def test_no_credentials_401(async_session):
    """无凭证返回 401。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=None, bearer=None, session=async_session)
    assert exc_info.value.status_code == 401


# ---------- get_current_admin_user 测试 ----------

@pytest.mark.asyncio
async def test_admin_user_success(async_session, admin_user_with_key):
    """管理员用户认证成功。"""
    admin_user, raw_key = admin_user_with_key
    result = await get_current_admin_user(api_key=raw_key, bearer=None, session=async_session)
    assert result.id == admin_user.id
    assert result.is_admin is True


@pytest.mark.asyncio
async def test_non_admin_user_403(async_session, normal_user_with_key):
    """非管理员用户返回 403。"""
    from fastapi import HTTPException
    _, raw_key = normal_user_with_key
    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin_user(api_key=raw_key, bearer=None, session=async_session)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_api_key_bootstrap(async_session):
    """ADMIN_API_KEY 返回 BOOTSTRAP_ADMIN。"""
    result = await get_current_admin_user(
        api_key=ADMIN_API_KEY_VALUE, bearer=None, session=async_session
    )
    assert result.id == BOOTSTRAP_ADMIN.id
    assert result.name == "bootstrap"
    assert result.is_admin is True


@pytest.mark.asyncio
async def test_admin_api_key_not_for_current_user(async_session):
    """ADMIN_API_KEY 不可用于 get_current_user（它不是数据库中的 Key）。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(api_key=ADMIN_API_KEY_VALUE, bearer=None, session=async_session)
    assert exc_info.value.status_code == 401
