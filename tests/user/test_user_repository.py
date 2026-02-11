"""UserRepository 集成测试。"""

import pytest

from src.user.domain.models import UserDomain, ApiKeyInfo
from src.user.infrastructure.repository import UserRepository, DuplicateError, NotFoundError


@pytest.mark.asyncio
async def test_create_user_success(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "hashed_pw")

    assert isinstance(user, UserDomain)
    assert user.name == "Alice"
    assert user.email == "alice@example.com"
    assert user.is_admin is False
    assert user.id is not None


@pytest.mark.asyncio
async def test_create_user_duplicate_email(async_session):
    repo = UserRepository(async_session)
    await repo.create_user("Alice", "alice@example.com", "hashed_pw")

    with pytest.raises(DuplicateError, match="该邮箱已被注册"):
        await repo.create_user("Bob", "alice@example.com", "hashed_pw2")


@pytest.mark.asyncio
async def test_get_user_by_id(async_session):
    repo = UserRepository(async_session)
    created = await repo.create_user("Alice", "alice@example.com", "hashed_pw")

    found = await repo.get_user_by_id(created.id)
    assert found is not None
    assert found.id == created.id
    assert found.email == "alice@example.com"


@pytest.mark.asyncio
async def test_get_user_by_email(async_session):
    repo = UserRepository(async_session)
    await repo.create_user("Alice", "alice@example.com", "hashed_pw")

    found = await repo.get_user_by_email("alice@example.com")
    assert found is not None
    assert found.name == "Alice"


@pytest.mark.asyncio
async def test_get_user_not_found(async_session):
    repo = UserRepository(async_session)

    assert await repo.get_user_by_id(9999) is None
    assert await repo.get_user_by_email("nobody@example.com") is None


@pytest.mark.asyncio
async def test_get_all_users(async_session):
    repo = UserRepository(async_session)
    await repo.create_user("Alice", "alice@example.com", "h1")
    await repo.create_user("Bob", "bob@example.com", "h2")

    users = await repo.get_all_users()
    assert len(users) == 2
    names = {u.name for u in users}
    assert names == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_create_api_key(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "hashed_pw")

    key_info = await repo.create_api_key(user.id, "hash123", "sna_1234", "my-key")
    assert isinstance(key_info, ApiKeyInfo)
    assert key_info.user_id == user.id
    assert key_info.key_prefix == "sna_1234"
    assert key_info.name == "my-key"
    assert key_info.is_active is True


@pytest.mark.asyncio
async def test_get_active_key_by_hash(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "hashed_pw")
    await repo.create_api_key(user.id, "hash_abc", "sna_abcd", "default")

    result = await repo.get_active_key_by_hash("hash_abc")
    assert result is not None
    key_info, user_id = result
    assert user_id == user.id
    assert key_info.key_prefix == "sna_abcd"

    # 不存在的 hash 应返回 None
    assert await repo.get_active_key_by_hash("nonexistent") is None


@pytest.mark.asyncio
async def test_get_keys_by_user(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "hashed_pw")
    await repo.create_api_key(user.id, "hash1", "sna_0001", "key1")
    await repo.create_api_key(user.id, "hash2", "sna_0002", "key2")

    keys = await repo.get_keys_by_user(user.id)
    assert len(keys) == 2
    names = {k.name for k in keys}
    assert names == {"key1", "key2"}


@pytest.mark.asyncio
async def test_deactivate_key(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "hashed_pw")
    key_info = await repo.create_api_key(user.id, "hash_deact", "sna_deac", "default")

    # 去活
    await repo.deactivate_key(key_info.id)

    # 去活后不应被 hash 查询返回
    result = await repo.get_active_key_by_hash("hash_deact")
    assert result is None

    # 去活不存在的 key 应抛出 NotFoundError
    with pytest.raises(NotFoundError):
        await repo.deactivate_key(9999)


@pytest.mark.asyncio
async def test_update_key_last_used(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "hashed_pw")
    key_info = await repo.create_api_key(user.id, "hash_lu", "sna_lu00", "default")
    assert key_info.last_used_at is None

    await repo.update_key_last_used(key_info.id)

    # 重新查询验证 last_used_at 已更新
    result = await repo.get_active_key_by_hash("hash_lu")
    assert result is not None
    updated_key, _ = result
    assert updated_key.last_used_at is not None


@pytest.mark.asyncio
async def test_update_password_hash(async_session):
    repo = UserRepository(async_session)
    user = await repo.create_user("Alice", "alice@example.com", "old_hash")

    await repo.update_password_hash(user.id, "new_hash")

    # 通过 ORM 对象验证
    orm_user = await repo.get_user_orm_by_id(user.id)
    assert orm_user is not None
    assert orm_user.password_hash == "new_hash"
