"""UserService 集成测试。"""

import pytest

from src.user.domain.models import UserDomain, ApiKeyInfo
from src.user.infrastructure.repository import DuplicateError, NotFoundError
from src.user.services.user_service import UserService


@pytest.mark.asyncio
async def test_create_user_success(async_session):
    svc = UserService(async_session)
    user, temp_password, raw_api_key = await svc.create_user("Alice", "alice@example.com")

    assert isinstance(user, UserDomain)
    assert user.name == "Alice"
    assert user.email == "alice@example.com"
    assert len(temp_password) == 12
    assert raw_api_key.startswith("sna_")


@pytest.mark.asyncio
async def test_create_user_duplicate_email(async_session):
    svc = UserService(async_session)
    await svc.create_user("Alice", "alice@example.com")

    with pytest.raises(DuplicateError):
        await svc.create_user("Bob", "alice@example.com")


@pytest.mark.asyncio
async def test_create_api_key(async_session):
    svc = UserService(async_session)
    user, _, _ = await svc.create_user("Alice", "alice@example.com")

    key_info, raw_key = await svc.create_api_key(user.id, "second-key")
    assert isinstance(key_info, ApiKeyInfo)
    assert key_info.name == "second-key"
    assert raw_key.startswith("sna_")

    # list 应返回 2 个 key（default + second-key）
    keys = await svc.list_api_keys(user.id)
    assert len(keys) == 2


@pytest.mark.asyncio
async def test_revoke_api_key_success(async_session):
    svc = UserService(async_session)
    user, _, _ = await svc.create_user("Alice", "alice@example.com")

    key_info, _ = await svc.create_api_key(user.id, "to-revoke")
    await svc.revoke_api_key(user.id, key_info.id)

    # 撤销后仍然在列表中，但 is_active 应为 False
    keys = await svc.list_api_keys(user.id)
    revoked = [k for k in keys if k.id == key_info.id]
    assert len(revoked) == 1
    assert revoked[0].is_active is False


@pytest.mark.asyncio
async def test_revoke_api_key_wrong_user(async_session):
    svc = UserService(async_session)
    user1, _, _ = await svc.create_user("Alice", "alice@example.com")
    user2, _, _ = await svc.create_user("Bob", "bob@example.com")

    key_info, _ = await svc.create_api_key(user1.id, "alice-key")

    # Bob 不能撤销 Alice 的 key
    with pytest.raises(NotFoundError):
        await svc.revoke_api_key(user2.id, key_info.id)


@pytest.mark.asyncio
async def test_change_password_success(async_session):
    svc = UserService(async_session)
    user, temp_password, _ = await svc.create_user("Alice", "alice@example.com")

    # 用临时密码修改为新密码
    await svc.change_password(user.id, temp_password, "NewSecurePass123")

    # 新密码可以验证
    from src.user.services.auth_service import AuthService
    auth = AuthService()
    orm_user = await svc._repo.get_user_orm_by_id(user.id)
    assert await auth.verify_password("NewSecurePass123", orm_user.password_hash)


@pytest.mark.asyncio
async def test_change_password_wrong_old(async_session):
    svc = UserService(async_session)
    user, _, _ = await svc.create_user("Alice", "alice@example.com")

    with pytest.raises(ValueError, match="旧密码不正确"):
        await svc.change_password(user.id, "wrong_old_password", "NewPass123")


@pytest.mark.asyncio
async def test_reset_password(async_session):
    svc = UserService(async_session)
    user, _, _ = await svc.create_user("Alice", "alice@example.com")

    new_temp = await svc.reset_password(user.id)
    assert len(new_temp) == 12

    # 新临时密码可以验证
    from src.user.services.auth_service import AuthService
    auth = AuthService()
    orm_user = await svc._repo.get_user_orm_by_id(user.id)
    assert await auth.verify_password(new_temp, orm_user.password_hash)
