"""ScraperConfigService 单元测试。

测试平台抓取配置服务的业务逻辑。
"""

import pytest

from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
    NotFoundError,
    DuplicateError,
)
from src.preference.services.scraper_config_service import ScraperConfigService


@pytest.mark.asyncio
class TestScraperConfigService:
    """ScraperConfigService 测试类。"""

    async def test_add_scraper_follow_success(self, async_session):
        """测试成功添加抓取账号。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)

        # Act
        result = await service.add_scraper_follow(
            username="testuser",
            reason="测试账号",
            added_by="admin"
        )

        # Assert
        assert isinstance(result, ScraperFollow)
        assert result.username == "testuser"
        assert result.reason == "测试账号"
        assert result.added_by == "admin"
        assert result.is_active is True
        assert result.id > 0

    async def test_add_scraper_follow_duplicate_raises_error(self, async_session):
        """测试添加重复账号时抛出错误。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow(
            username="testuser",
            reason="测试账号",
            added_by="admin"
        )

        # Act & Assert
        with pytest.raises(DuplicateError) as exc_info:
            await service.add_scraper_follow(
                username="testuser",
                reason="重复账号",
                added_by="admin"
            )
        assert "testuser" in str(exc_info.value)

    async def test_get_all_follows_returns_active_only_by_default(self, async_session):
        """测试默认只返回启用的抓取账号。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("user1", "原因1", "admin")
        await service.add_scraper_follow("user2", "原因2", "admin")
        await service.add_scraper_follow("user3", "原因3", "admin")
        # 禁用一个账号
        await service.deactivate_follow("user2")

        # Act
        result = await service.get_all_follows()

        # Assert
        assert len(result) == 2
        usernames = [f.username for f in result]
        assert "user1" in usernames
        assert "user3" in usernames
        assert "user2" not in usernames

    async def test_get_all_follows_with_inactive(self, async_session):
        """测试包含禁用账号时返回所有账号。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("user1", "原因1", "admin")
        await service.add_scraper_follow("user2", "原因2", "admin")
        await service.deactivate_follow("user2")

        # Act
        result = await service.get_all_follows(include_inactive=True)

        # Assert
        assert len(result) == 2
        usernames = [f.username for f in result]
        assert "user1" in usernames
        assert "user2" in usernames

    async def test_update_follow_reason(self, async_session):
        """测试更新抓取账号的理由。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("testuser", "原始理由", "admin")

        # Act
        result = await service.update_follow(
            username="testuser",
            reason="更新后的理由"
        )

        # Assert
        assert result.reason == "更新后的理由"
        assert result.is_active is True  # 状态未变

    async def test_update_follow_is_active(self, async_session):
        """测试禁用/启用抓取账号。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("testuser", "理由", "admin")

        # Act - 禁用
        result = await service.update_follow(
            username="testuser",
            is_active=False
        )

        # Assert
        assert result.is_active is False

        # Act - 重新启用
        result = await service.update_follow(
            username="testuser",
            is_active=True
        )

        # Assert
        assert result.is_active is True

    async def test_update_follow_not_found_raises_error(self, async_session):
        """测试更新不存在的账号时抛出错误。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await service.update_follow(
                username="nonexistent",
                reason="新理由"
            )
        assert "nonexistent" in str(exc_info.value)

    async def test_deactivate_follow_success(self, async_session):
        """测试成功禁用抓取账号。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("testuser", "理由", "admin")

        # Act
        await service.deactivate_follow("testuser")

        # Assert
        result = await service.get_all_follows(include_inactive=True)
        testuser = next(f for f in result if f.username == "testuser")
        assert testuser.is_active is False

    async def test_deactivate_follow_not_found_raises_error(self, async_session):
        """测试禁用不存在的账号时抛出错误。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await service.deactivate_follow("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    async def test_is_username_in_follows_true(self, async_session):
        """测试检查存在的用户名返回 True。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("testuser", "理由", "admin")

        # Act
        result = await service.is_username_in_follows("testuser")

        # Assert
        assert result is True

    async def test_is_username_in_follows_false(self, async_session):
        """测试检查不存在的用户名返回 False。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)

        # Act
        result = await service.is_username_in_follows("nonexistent")

        # Assert
        assert result is False

    async def test_is_username_in_follows_inactive_account(self, async_session):
        """测试检查禁用的账号（active_only=True 时返回 False）。"""
        # Arrange
        repository = ScraperConfigRepository(async_session)
        service = ScraperConfigService(repository)
        await service.add_scraper_follow("testuser", "理由", "admin")
        await service.deactivate_follow("testuser")

        # Act - 默认只检查启用的
        result_active = await service.is_username_in_follows("testuser")

        # Assert
        assert result_active is False

        # Act - 检查所有
        result_all = await service.is_username_in_follows("testuser", active_only=False)

        # Assert
        assert result_all is True
