"""PreferenceRepository 单元测试。

测试用户关注列表数据访问层的 CRUD 操作。
"""

import pytest
from datetime import datetime, timezone

from src.database.models import TwitterFollow
from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    RepositoryError,
    NotFoundError,
    DuplicateError,
)
from src.preference.domain.models import TwitterFollow as TwitterFollowDomain


class TestTwitterFollowCRUD:
    """测试 TwitterFollow CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_create_follow_success(self, async_session):
        """测试成功创建关注记录。"""
        repo = PreferenceRepository(async_session)

        # 创建测试用户
        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建关注
        follow = await repo.create_follow(
            user_id=user.id,
            username="karpathy",
        )

        assert follow.id > 0
        assert follow.user_id == user.id
        assert follow.username == "karpathy"
        assert isinstance(follow.created_at, datetime)

    @pytest.mark.asyncio
    async def test_create_follow_duplicate_raises_error(self, async_session):
        """测试创建重复关注时抛出错误。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 第一次创建
        await repo.create_follow(user_id=user.id, username="karpathy")

        # 第二次创建同样用户名应该失败
        with pytest.raises(DuplicateError) as exc_info:
            await repo.create_follow(user_id=user.id, username="karpathy")

        assert "已存在" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_follow_by_username_success(self, async_session):
        """测试根据用户名查询关注记录。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建关注
        await repo.create_follow(user_id=user.id, username="samalt")

        # 查询关注
        follow = await repo.get_follow_by_username(user.id, "samalt")

        assert follow is not None
        assert follow.username == "samalt"
        assert follow.user_id == user.id

    @pytest.mark.asyncio
    async def test_get_follow_by_username_not_found(self, async_session):
        """测试查询不存在的关注记录返回 None。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        follow = await repo.get_follow_by_username(user.id, "nonexistent")

        assert follow is None

    @pytest.mark.asyncio
    async def test_get_follows_by_user(self, async_session):
        """测试查询用户的所有关注记录。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建多个关注
        await repo.create_follow(user_id=user.id, username="user1")
        await repo.create_follow(user_id=user.id, username="user2")
        await repo.create_follow(user_id=user.id, username="user3")

        # 查询所有关注
        follows = await repo.get_follows_by_user(user.id)

        assert len(follows) == 3
        usernames = {f.username for f in follows}
        assert usernames == {"user1", "user2", "user3"}

    @pytest.mark.asyncio
    async def test_get_follows_by_user_empty(self, async_session):
        """测试查询没有关注的用户返回空列表。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        follows = await repo.get_follows_by_user(user.id)

        assert follows == []

    @pytest.mark.asyncio
    async def test_delete_follow_success(self, async_session):
        """测试删除关注记录。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建关注
        await repo.create_follow(user_id=user.id, username="karpathy")

        # 删除关注
        await repo.delete_follow(user.id, "karpathy")

        # 验证删除
        follow = await repo.get_follow_by_username(user.id, "karpathy")
        assert follow is None

    @pytest.mark.asyncio
    async def test_delete_follow_not_found(self, async_session):
        """测试删除不存在的关注不抛出错误（幂等操作）。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 删除不存在的关注不应该抛出错误
        await repo.delete_follow(user.id, "nonexistent")

    @pytest.mark.asyncio
    async def test_user_has_follows_initialized(self, async_session):
        """测试检查用户关注列表是否已初始化。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 未初始化
        assert not await repo.user_has_follows(user.id)

        # 添加关注后
        await repo.create_follow(user_id=user.id, username="karpathy")
        assert await repo.user_has_follows(user.id)

    @pytest.mark.asyncio
    async def test_batch_create_follows(self, async_session):
        """测试批量创建关注记录。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 批量创建
        usernames = ["user1", "user2", "user3"]
        follows = await repo.batch_create_follows(user.id, usernames)

        assert len(follows) == 3
        for follow in follows:
            assert follow.user_id == user.id
            assert follow.username in usernames


class TestTransactionHandling:
    """测试事务处理。"""

    @pytest.mark.asyncio
    async def test_batch_create_follows_duplicate_raises_error(self, async_session):
        """测试批量创建关注时遇到重复用户名抛出错误。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        user_id = user.id  # 保存 ID

        # 创建一个已存在的用户名
        await repo.create_follow(user_id=user_id, username="existing_user")

        # 提交第一个创建操作
        await async_session.commit()

        # 批量创建包含重复用户名，应该抛出错误
        with pytest.raises(DuplicateError):
            await repo.batch_create_follows(user_id, ["user1", "existing_user", "user3"])

        # 验证新用户没有被创建（只有原来的 existing_user）
        follows = await repo.get_follows_by_user(user_id)
        assert len(follows) == 1
        assert follows[0].username == "existing_user"
