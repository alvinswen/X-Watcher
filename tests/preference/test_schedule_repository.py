"""ScraperScheduleRepository 单元测试。"""

import pytest
from datetime import datetime, timezone

from src.preference.infrastructure.schedule_repository import (
    ScraperScheduleRepository,
)


class TestScraperScheduleRepository:
    """测试调度配置 Repository。"""

    @pytest.mark.asyncio
    async def test_get_schedule_config_empty_table(self, async_session):
        """空表查询应返回 None。"""
        repo = ScraperScheduleRepository(async_session)
        result = await repo.get_schedule_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_creates_new_config(self, async_session):
        """首次 upsert 应创建新配置记录。"""
        repo = ScraperScheduleRepository(async_session)
        result = await repo.upsert_schedule_config(
            interval_seconds=600,
            updated_by="admin",
        )
        await async_session.commit()

        assert result.id == 1
        assert result.interval_seconds == 600
        assert result.next_run_time is None
        assert result.is_enabled is True
        assert result.updated_by == "admin"
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_config(self, async_session):
        """已存在配置时 upsert 应更新。"""
        repo = ScraperScheduleRepository(async_session)

        # 创建初始配置
        await repo.upsert_schedule_config(
            interval_seconds=600,
            updated_by="admin1",
        )
        await async_session.commit()

        # 更新配置
        result = await repo.upsert_schedule_config(
            interval_seconds=1200,
            updated_by="admin2",
        )
        await async_session.commit()

        assert result.id == 1
        assert result.interval_seconds == 1200
        assert result.updated_by == "admin2"

    @pytest.mark.asyncio
    async def test_upsert_partial_update_interval_only(self, async_session):
        """仅更新 interval_seconds，next_run_time 保持不变。"""
        repo = ScraperScheduleRepository(async_session)
        next_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

        # 创建带 next_run_time 的配置
        await repo.upsert_schedule_config(
            interval_seconds=600,
            next_run_time=next_time,
            updated_by="admin",
        )
        await async_session.commit()

        # 仅更新间隔
        result = await repo.upsert_schedule_config(
            interval_seconds=1200,
            updated_by="admin",
        )
        await async_session.commit()

        assert result.interval_seconds == 1200
        # next_run_time 应保持不变
        assert result.next_run_time is not None

    @pytest.mark.asyncio
    async def test_upsert_partial_update_next_run_time_only(self, async_session):
        """仅更新 next_run_time，interval_seconds 保持不变。"""
        repo = ScraperScheduleRepository(async_session)
        next_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

        # 创建初始配置
        await repo.upsert_schedule_config(
            interval_seconds=600,
            updated_by="admin",
        )
        await async_session.commit()

        # 仅更新触发时间
        result = await repo.upsert_schedule_config(
            next_run_time=next_time,
            updated_by="admin",
        )
        await async_session.commit()

        assert result.interval_seconds == 600
        assert result.next_run_time == next_time

    @pytest.mark.asyncio
    async def test_get_schedule_config_after_upsert(self, async_session):
        """upsert 后 get 应返回配置。"""
        repo = ScraperScheduleRepository(async_session)
        await repo.upsert_schedule_config(
            interval_seconds=900,
            updated_by="admin",
        )
        await async_session.commit()

        result = await repo.get_schedule_config()
        assert result is not None
        assert result.interval_seconds == 900
        assert result.updated_by == "admin"

    @pytest.mark.asyncio
    async def test_upsert_is_enabled_field(self, async_session):
        """测试 is_enabled 字段的创建和更新。"""
        repo = ScraperScheduleRepository(async_session)

        # 创建配置（默认 is_enabled=True）
        result = await repo.upsert_schedule_config(
            interval_seconds=600,
            updated_by="admin",
        )
        await async_session.commit()
        assert result.is_enabled is True

        # 更新为 False
        result = await repo.upsert_schedule_config(
            is_enabled=False,
            updated_by="admin",
        )
        await async_session.commit()
        assert result.is_enabled is False

        # 重新启用
        result = await repo.upsert_schedule_config(
            is_enabled=True,
            updated_by="admin",
        )
        await async_session.commit()
        assert result.is_enabled is True

    @pytest.mark.asyncio
    async def test_upsert_is_enabled_not_affected_by_other_updates(self, async_session):
        """更新 interval 不应影响 is_enabled。"""
        repo = ScraperScheduleRepository(async_session)

        # 创建并禁用
        await repo.upsert_schedule_config(
            interval_seconds=600,
            is_enabled=False,
            updated_by="admin",
        )
        await async_session.commit()

        # 仅更新 interval（不传 is_enabled）
        result = await repo.upsert_schedule_config(
            interval_seconds=1200,
            updated_by="admin",
        )
        await async_session.commit()

        assert result.interval_seconds == 1200
        assert result.is_enabled is False  # 不受影响
