"""ScraperScheduleService 单元测试。

使用 mock Repository 和 scheduler_accessor 测试业务逻辑。
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.preference.services.schedule_service import ScraperScheduleService
from src.preference.domain.models import ScraperScheduleConfig


class TestGetScheduleConfig:
    """测试查看调度配置。"""

    @pytest.mark.asyncio
    async def test_get_config_with_db_config_and_running_scheduler(self):
        """有 DB 配置且调度器运行时，返回 DB 配置 + 调度器状态。"""
        db_config = ScraperScheduleConfig(
            id=1,
            interval_seconds=600,
            next_run_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.next_run_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_scheduler.get_job.return_value = mock_job

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler):
            result = await service.get_schedule_config()

        assert result.interval_seconds == 600
        assert result.scheduler_running is True
        assert result.next_run_time is not None
        assert result.updated_by == "admin"
        assert result.message is None

    @pytest.mark.asyncio
    async def test_get_config_without_db_config(self):
        """无 DB 配置时，使用环境变量默认值。"""
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = None

        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.next_run_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_scheduler.get_job.return_value = mock_job

        service = ScraperScheduleService(mock_repo)

        with (
            patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler),
            patch("src.preference.services.schedule_service.get_settings") as mock_settings,
        ):
            mock_settings.return_value.scraper_interval = 43200
            result = await service.get_schedule_config()

        assert result.interval_seconds == 43200
        assert result.scheduler_running is True

    @pytest.mark.asyncio
    async def test_get_config_scheduler_not_running(self):
        """调度器未运行时，返回 scheduler_running=False。"""
        db_config = ScraperScheduleConfig(
            id=1,
            interval_seconds=600,
            next_run_time=None,
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = db_config

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            result = await service.get_schedule_config()

        assert result.scheduler_running is False
        assert result.interval_seconds == 600


class TestUpdateInterval:
    """测试更新抓取间隔。"""

    @pytest.mark.asyncio
    async def test_update_interval_with_running_scheduler(self):
        """调度器运行时，更新间隔并同步调度器。"""
        db_config = ScraperScheduleConfig(
            id=1,
            interval_seconds=1200,
            next_run_time=None,
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.next_run_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_scheduler.get_job.return_value = mock_job

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler):
            result = await service.update_interval(1200, "admin")

        mock_repo.upsert_schedule_config.assert_called_once_with(
            interval_seconds=1200, updated_by="admin"
        )
        mock_scheduler.reschedule_job.assert_called_once_with(
            "scraper_job", trigger="interval", seconds=1200
        )
        assert result.interval_seconds == 1200
        assert result.scheduler_running is True

    @pytest.mark.asyncio
    async def test_update_interval_scheduler_not_running(self):
        """调度器未运行时，仍持久化配置。"""
        db_config = ScraperScheduleConfig(
            id=1,
            interval_seconds=1200,
            next_run_time=None,
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            result = await service.update_interval(1200, "admin")

        mock_repo.upsert_schedule_config.assert_called_once()
        assert result.scheduler_running is False
        assert result.message is not None


class TestUpdateNextRunTime:
    """测试设置下次触发时间。"""

    @pytest.mark.asyncio
    async def test_update_next_run_time_valid(self):
        """有效的未来时间应成功更新。"""
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        db_config = ScraperScheduleConfig(
            id=1,
            interval_seconds=600,
            next_run_time=future_time,
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.next_run_time = future_time
        mock_scheduler.get_job.return_value = mock_job

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler):
            result = await service.update_next_run_time(future_time, "admin")

        mock_scheduler.modify_job.assert_called_once_with(
            "scraper_job", next_run_time=future_time
        )
        assert result.scheduler_running is True

    @pytest.mark.asyncio
    async def test_update_next_run_time_past_rejected(self):
        """过去时间应被拒绝。"""
        past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        mock_repo = AsyncMock()

        service = ScraperScheduleService(mock_repo)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await service.update_next_run_time(past_time, "admin")

        assert exc_info.value.status_code == 422
        mock_repo.upsert_schedule_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_next_run_time_too_far_rejected(self):
        """超过 30 天的时间应被拒绝。"""
        far_time = datetime.now(timezone.utc) + timedelta(days=31)
        mock_repo = AsyncMock()

        service = ScraperScheduleService(mock_repo)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await service.update_next_run_time(far_time, "admin")

        assert exc_info.value.status_code == 422
        mock_repo.upsert_schedule_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_next_run_time_scheduler_not_running(self):
        """调度器未运行时仍持久化。"""
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        db_config = ScraperScheduleConfig(
            id=1,
            interval_seconds=600,
            next_run_time=future_time,
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            result = await service.update_next_run_time(future_time, "admin")

        mock_repo.upsert_schedule_config.assert_called_once()
        assert result.scheduler_running is False
        assert result.message is not None
