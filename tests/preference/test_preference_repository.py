"""PreferenceRepository 单元测试。

测试用户偏好数据访问层的 CRUD 操作。
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.database.models import TwitterFollow, FilterRule, Preference
from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    RepositoryError,
    NotFoundError,
    DuplicateError,
)
from src.preference.domain.models import TwitterFollow as TwitterFollowDomain, FilterRule as FilterRuleDomain, FilterType


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
            priority=8
        )

        assert follow.id > 0
        assert follow.user_id == user.id
        assert follow.username == "karpathy"
        assert follow.priority == 8
        assert isinstance(follow.created_at, datetime)
        assert isinstance(follow.updated_at, datetime)

    @pytest.mark.asyncio
    async def test_create_follow_default_priority(self, async_session):
        """测试创建关注时使用默认优先级。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 不指定优先级
        follow = await repo.create_follow(
            user_id=user.id,
            username="ylecun"
        )

        assert follow.priority == 5  # 默认优先级

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
        await repo.create_follow(user_id=user.id, username="user1", priority=3)
        await repo.create_follow(user_id=user.id, username="user2", priority=7)
        await repo.create_follow(user_id=user.id, username="user3", priority=5)

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
    async def test_update_follow_priority(self, async_session):
        """测试更新关注优先级。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建关注
        follow = await repo.create_follow(user_id=user.id, username="karpathy", priority=5)

        # 更新优先级
        updated_follow = await repo.update_follow_priority(
            user.id, "karpathy", 9
        )

        assert updated_follow.priority == 9
        assert updated_follow.username == "karpathy"
        # 更新时间应该改变
        assert updated_follow.updated_at >= follow.updated_at

    @pytest.mark.asyncio
    async def test_update_follow_priority_not_found(self, async_session):
        """测试更新不存在的关注优先级抛出错误。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        with pytest.raises(NotFoundError):
            await repo.update_follow_priority(user.id, "nonexistent", 5)

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
            assert follow.priority == 5  # 默认优先级


class TestFilterRuleCRUD:
    """测试 FilterRule CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_create_filter_keyword_success(self, async_session):
        """测试成功创建关键词过滤规则。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        filter_rule = await repo.create_filter(
            user_id=user.id,
            filter_type=FilterType.KEYWORD,
            value="AI"
        )

        assert filter_rule.id is not None
        assert len(filter_rule.id) == 36  # UUID 格式
        assert filter_rule.user_id == user.id
        assert filter_rule.filter_type == FilterType.KEYWORD
        assert filter_rule.value == "AI"
        assert isinstance(filter_rule.created_at, datetime)

    @pytest.mark.asyncio
    async def test_create_filter_hashtag_success(self, async_session):
        """测试成功创建话题标签过滤规则。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        filter_rule = await repo.create_filter(
            user_id=user.id,
            filter_type=FilterType.HASHTAG,
            value="python"
        )

        assert filter_rule.filter_type == FilterType.HASHTAG
        assert filter_rule.value == "python"

    @pytest.mark.asyncio
    async def test_create_filter_content_type_success(self, async_session):
        """测试成功创建内容类型过滤规则。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        filter_rule = await repo.create_filter(
            user_id=user.id,
            filter_type=FilterType.CONTENT_TYPE,
            value="retweet"
        )

        assert filter_rule.filter_type == FilterType.CONTENT_TYPE
        assert filter_rule.value == "retweet"

    @pytest.mark.asyncio
    async def test_get_filters_by_user(self, async_session):
        """测试查询用户的所有过滤规则。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建多个过滤规则
        await repo.create_filter(user_id=user.id, filter_type=FilterType.KEYWORD, value="AI")
        await repo.create_filter(user_id=user.id, filter_type=FilterType.HASHTAG, value="python")
        await repo.create_filter(user_id=user.id, filter_type=FilterType.CONTENT_TYPE, value="retweet")

        # 查询所有过滤规则
        filters = await repo.get_filters_by_user(user.id)

        assert len(filters) == 3
        filter_types = {f.filter_type for f in filters}
        assert filter_types == {FilterType.KEYWORD, FilterType.HASHTAG, FilterType.CONTENT_TYPE}

    @pytest.mark.asyncio
    async def test_get_filter_by_id_success(self, async_session):
        """测试根据 ID 查询过滤规则。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建过滤规则
        created_filter = await repo.create_filter(
            user_id=user.id,
            filter_type=FilterType.KEYWORD,
            value="LLM"
        )

        # 根据 ID 查询
        filter_rule = await repo.get_filter_by_id(created_filter.id)

        assert filter_rule is not None
        assert filter_rule.id == created_filter.id
        assert filter_rule.value == "LLM"

    @pytest.mark.asyncio
    async def test_get_filter_by_id_not_found(self, async_session):
        """测试查询不存在的过滤规则返回 None。"""
        repo = PreferenceRepository(async_session)

        filter_rule = await repo.get_filter_by_id("nonexistent-uuid")

        assert filter_rule is None

    @pytest.mark.asyncio
    async def test_delete_filter_success(self, async_session):
        """测试删除过滤规则。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 创建过滤规则
        filter_rule = await repo.create_filter(
            user_id=user.id,
            filter_type=FilterType.KEYWORD,
            value="AI"
        )

        # 删除过滤规则
        await repo.delete_filter(filter_rule.id)

        # 验证删除
        deleted_filter = await repo.get_filter_by_id(filter_rule.id)
        assert deleted_filter is None

    @pytest.mark.asyncio
    async def test_delete_filter_not_found(self, async_session):
        """测试删除不存在的过滤规则不抛出错误。"""
        repo = PreferenceRepository(async_session)

        # 删除不存在的过滤规则不应该抛出错误
        await repo.delete_filter("nonexistent-uuid")


class TestPreferenceCRUD:
    """测试 Preference 简单配置 CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_set_preference_success(self, async_session):
        """测试成功设置偏好配置。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 设置偏好
        await repo.set_preference(user.id, "sort_type", "time")

        # 获取偏好
        value = await repo.get_preference(user.id, "sort_type")

        assert value == "time"

    @pytest.mark.asyncio
    async def test_set_preference_update_existing(self, async_session):
        """测试更新已存在的偏好配置。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 设置偏好
        await repo.set_preference(user.id, "sort_type", "time")

        # 更新偏好
        await repo.set_preference(user.id, "sort_type", "relevance")

        # 获取更新后的偏好
        value = await repo.get_preference(user.id, "sort_type")

        assert value == "relevance"

    @pytest.mark.asyncio
    async def test_get_preference_not_found(self, async_session):
        """测试获取不存在的偏好返回 None。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        value = await repo.get_preference(user.id, "nonexistent_key")

        assert value is None

    @pytest.mark.asyncio
    async def test_get_all_preferences(self, async_session):
        """测试获取用户的所有偏好配置。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 设置多个偏好
        await repo.set_preference(user.id, "sort_type", "time")
        await repo.set_preference(user.id, "items_per_page", "50")
        await repo.set_preference(user.id, "theme", "dark")

        # 获取所有偏好
        preferences = await repo.get_all_preferences(user.id)

        assert len(preferences) == 3
        assert preferences["sort_type"] == "time"
        assert preferences["items_per_page"] == "50"
        assert preferences["theme"] == "dark"

    @pytest.mark.asyncio
    async def test_delete_preference_success(self, async_session):
        """测试删除偏好配置。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 设置偏好
        await repo.set_preference(user.id, "sort_type", "time")

        # 删除偏好
        await repo.delete_preference(user.id, "sort_type")

        # 验证删除
        value = await repo.get_preference(user.id, "sort_type")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_preference_not_found(self, async_session):
        """测试删除不存在的偏好不抛出错误。"""
        repo = PreferenceRepository(async_session)

        from src.database.models import User
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()

        # 删除不存在的偏好不应该抛出错误
        await repo.delete_preference(user.id, "nonexistent_key")


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
