"""ScraperConfigRepository 单元测试。

测试平台抓取配置数据访问层的 CRUD 操作。
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy import select

from src.database.models import ScraperFollow
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
    RepositoryError,
    NotFoundError,
    DuplicateError,
)
from src.preference.domain.models import ScraperFollow as ScraperFollowDomain


class TestScraperFollowCRUD:
    """测试 ScraperFollow CRUD 操作。"""

    @pytest.mark.asyncio
    async def test_create_scraper_follow_success(self, async_session):
        """测试成功创建抓取账号记录。"""
        repo = ScraperConfigRepository(async_session)

        follow = await repo.create_scraper_follow(
            username="karpathy",
            reason="AI researcher",
            added_by="admin"
        )

        assert follow.id > 0
        assert follow.username == "karpathy"
        assert follow.reason == "AI researcher"
        assert follow.added_by == "admin"
        assert follow.is_active is True
        assert isinstance(follow.added_at, datetime)

    @pytest.mark.asyncio
    async def test_create_scraper_follow_duplicate_raises_error(self, async_session):
        """测试创建重复抓取账号时抛出错误。"""
        repo = ScraperConfigRepository(async_session)

        # 第一次创建
        await repo.create_scraper_follow(
            username="karpathy",
            reason="AI researcher",
            added_by="admin"
        )

        # 第二次创建同样用户名应该失败
        with pytest.raises(DuplicateError):
            await repo.create_scraper_follow(
                username="karpathy",
                reason="Duplicate",
                added_by="admin"
            )

    @pytest.mark.asyncio
    async def test_get_all_follows_active_only(self, async_session):
        """测试获取所有启用的抓取账号。"""
        repo = ScraperConfigRepository(async_session)

        # 创建多个账号
        await repo.create_scraper_follow("user1", "reason1", "admin")
        await repo.create_scraper_follow("user2", "reason2", "admin")

        # 创建一个禁用的账号
        user3 = await repo.create_scraper_follow("user3", "reason3", "admin")
        await repo.update_scraper_follow("user3", is_active=False)

        # 获取启用的账号
        follows = await repo.get_all_follows(include_inactive=False)

        assert len(follows) == 2
        usernames = {f.username for f in follows}
        assert usernames == {"user1", "user2"}

    @pytest.mark.asyncio
    async def test_get_all_follows_include_inactive(self, async_session):
        """测试获取所有抓取账号（包括禁用的）。"""
        repo = ScraperConfigRepository(async_session)

        # 创建多个账号
        await repo.create_scraper_follow("user1", "reason1", "admin")
        await repo.create_scraper_follow("user2", "reason2", "admin")

        # 创建一个禁用的账号
        await repo.create_scraper_follow("user3", "reason3", "admin")
        await repo.update_scraper_follow("user3", is_active=False)

        # 获取所有账号
        follows = await repo.get_all_follows(include_inactive=True)

        assert len(follows) == 3
        usernames = {f.username for f in follows}
        assert usernames == {"user1", "user2", "user3"}

    @pytest.mark.asyncio
    async def test_get_all_follows_empty(self, async_session):
        """测试获取空列表。"""
        repo = ScraperConfigRepository(async_session)

        follows = await repo.get_all_follows()

        assert follows == []

    @pytest.mark.asyncio
    async def test_get_follow_by_username_success(self, async_session):
        """测试根据用户名查询抓取账号。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "AI researcher", "admin")

        follow = await repo.get_follow_by_username("karpathy")

        assert follow is not None
        assert follow.username == "karpathy"
        assert follow.reason == "AI researcher"

    @pytest.mark.asyncio
    async def test_get_follow_by_username_not_found(self, async_session):
        """测试查询不存在的账号返回 None。"""
        repo = ScraperConfigRepository(async_session)

        follow = await repo.get_follow_by_username("nonexistent")

        assert follow is None

    @pytest.mark.asyncio
    async def test_update_scraper_follow_reason(self, async_session):
        """测试更新抓取账号的理由。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "Old reason", "admin")

        updated = await repo.update_scraper_follow(
            "karpathy",
            reason="New reason"
        )

        assert updated.reason == "New reason"
        assert updated.username == "karpathy"
        assert updated.is_active is True  # 未改变

    @pytest.mark.asyncio
    async def test_update_scraper_follow_is_active(self, async_session):
        """测试更新抓取账号的启用状态。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "AI researcher", "admin")

        # 禁用账号
        updated = await repo.update_scraper_follow("karpathy", is_active=False)

        assert updated.is_active is False

        # 重新启用账号
        updated = await repo.update_scraper_follow("karpathy", is_active=True)

        assert updated.is_active is True

    @pytest.mark.asyncio
    async def test_update_scraper_follow_not_found(self, async_session):
        """测试更新不存在的账号抛出错误。"""
        repo = ScraperConfigRepository(async_session)

        with pytest.raises(NotFoundError):
            await repo.update_scraper_follow("nonexistent", reason="New reason")

    @pytest.mark.asyncio
    async def test_update_scraper_follow_no_changes(self, async_session):
        """测试不提供任何更新参数时抛出错误。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "AI researcher", "admin")

        # 不提供任何更新参数应该抛出错误
        with pytest.raises(RepositoryError):
            await repo.update_scraper_follow("karpathy")

    @pytest.mark.asyncio
    async def test_deactivate_follow_success(self, async_session):
        """测试禁用抓取账号。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "AI researcher", "admin")

        # 禁用账号
        await repo.deactivate_follow("karpathy")

        # 验证禁用状态
        follow = await repo.get_follow_by_username("karpathy")
        assert follow is not None
        assert follow.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_follow_not_found(self, async_session):
        """测试禁用不存在的账号抛出错误。"""
        repo = ScraperConfigRepository(async_session)

        with pytest.raises(NotFoundError):
            await repo.deactivate_follow("nonexistent")

    @pytest.mark.asyncio
    async def test_is_username_in_follows_active(self, async_session):
        """测试检查用户名是否在启用的抓取列表中。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "AI researcher", "admin")

        # 启用的账号应该返回 True
        assert await repo.is_username_in_follows("karpathy", active_only=True)
        assert await repo.is_username_in_follows("karpathy", active_only=False)

        # 不存在的账号应该返回 False
        assert not await repo.is_username_in_follows("nonexistent", active_only=True)
        assert not await repo.is_username_in_follows("nonexistent", active_only=False)

    @pytest.mark.asyncio
    async def test_is_username_in_follows_inactive(self, async_session):
        """测试检查用户名在禁用账号时的返回值。"""
        repo = ScraperConfigRepository(async_session)

        await repo.create_scraper_follow("karpathy", "AI researcher", "admin")
        await repo.deactivate_follow("karpathy")

        # 只查询启用的账号应该返回 False
        assert not await repo.is_username_in_follows("karpathy", active_only=True)

        # 查询所有账号应该返回 True
        assert await repo.is_username_in_follows("karpathy", active_only=False)

    @pytest.mark.asyncio
    async def test_get_active_follows(self, async_session):
        """测试获取所有启用的抓取账号。"""
        repo = ScraperConfigRepository(async_session)

        # 创建多个账号
        await repo.create_scraper_follow("user1", "reason1", "admin")
        await repo.create_scraper_follow("user2", "reason2", "admin")
        await repo.create_scraper_follow("user3", "reason3", "admin")

        # 禁用一个账号
        await repo.deactivate_follow("user2")

        # 获取启用的账号
        active_follows = await repo.get_active_follows()

        assert len(active_follows) == 2
        usernames = {f.username for f in active_follows}
        assert usernames == {"user1", "user3"}
