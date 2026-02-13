"""PreferenceService 单元测试。

测试用户关注列表管理服务的业务逻辑。
"""

import pytest

from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    NotFoundError,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
)
from src.preference.services.preference_service import PreferenceService


@pytest.mark.asyncio
class TestPreferenceService:
    """PreferenceService 测试类。"""

    async def test_initialize_user_follows_from_scraper_follows(self, async_session):
        """测试用户关注列表初始化 - 从抓取列表复制。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        service = PreferenceService(pref_repo, scraper_repo)

        # 添加抓取账号
        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")
        await scraper_repo.create_scraper_follow("user2", "理由2", "admin")
        await scraper_repo.create_scraper_follow("user3", "理由3", "admin")

        # Act - 初始化用户关注列表
        await service.initialize_user_follows(user_id=1)

        # Assert - 用户应该有 3 个关注
        follows = await pref_repo.get_follows_by_user(user_id=1)
        assert len(follows) == 3
        usernames = {f.username for f in follows}
        assert usernames == {"user1", "user2", "user3"}

    async def test_initialize_user_follows_skips_if_already_initialized(
        self, async_session
    ):
        """测试如果用户已有关注列表，跳过初始化。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        service = PreferenceService(pref_repo, scraper_repo)

        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")
        await scraper_repo.create_scraper_follow("user2", "理由2", "admin")

        # 手动添加一个用户关注
        await pref_repo.create_follow(1, "user1")

        # Act - 尝试初始化
        await service.initialize_user_follows(user_id=1)

        # Assert - 应该只有原有的关注，没有添加新的
        follows = await pref_repo.get_follows_by_user(user_id=1)
        assert len(follows) == 1
        assert follows[0].username == "user1"

    async def test_add_follow_validates_against_scraper_follows(self, async_session):
        """测试添加关注时验证账号在抓取列表中。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        service = PreferenceService(pref_repo, scraper_repo)

        # 只添加 user1 到抓取列表
        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")

        # Act - 添加存在的账号
        result = await service.add_follow(user_id=1, username="user1")

        # Assert
        assert result.username == "user1"

    async def test_add_follow_fails_if_not_in_scraper_follows(self, async_session):
        """测试添加不在抓取列表中的账号时失败。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        service = PreferenceService(pref_repo, scraper_repo)

        # 抓取列表为空

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await service.add_follow(user_id=1, username="nonexistent")
        assert "不在平台抓取列表中" in str(exc_info.value) or "抓取列表" in str(exc_info.value)

    async def test_remove_follow_success(self, async_session):
        """测试成功移除关注。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        service = PreferenceService(pref_repo, scraper_repo)

        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")
        await service.add_follow(user_id=1, username="user1")

        # Act
        await service.remove_follow(user_id=1, username="user1")

        # Assert
        follows = await pref_repo.get_follows_by_user(user_id=1)
        assert len(follows) == 0

    async def test_get_follows_returns_list(self, async_session):
        """测试获取关注列表。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        service = PreferenceService(pref_repo, scraper_repo)

        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")
        await scraper_repo.create_scraper_follow("user2", "理由2", "admin")
        await scraper_repo.create_scraper_follow("user3", "理由3", "admin")

        await service.add_follow(1, "user1")
        await service.add_follow(1, "user2")
        await service.add_follow(1, "user3")

        # Act
        follows = await service.get_follows(user_id=1)

        # Assert
        assert len(follows) == 3
        usernames = {f.username for f in follows}
        assert usernames == {"user1", "user2", "user3"}
