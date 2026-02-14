"""ScraperScheduleService 单元测试。

使用 mock Repository 和 scheduler_accessor 测试业务逻辑。
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.preference.services.schedule_service import ScraperScheduleService
from src.preference.domain.models import ScraperScheduleConfig


def _make_config(**overrides):
    """快捷构造 ScraperScheduleConfig。"""
    defaults = dict(
        id=1,
        interval_seconds=600,
        next_run_time=None,
        is_enabled=True,
        updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        updated_by="admin",
    )
    defaults.update(overrides)
    return ScraperScheduleConfig(**defaults)


class TestGetScheduleConfig:
    """测试查看调度配置。"""

    @pytest.mark.asyncio
    async def test_get_config_with_db_config_and_running_scheduler(self):
        """有 DB 配置且调度器运行时，返回 DB 配置 + 调度器状态。"""
        db_config = _make_config(
            next_run_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
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
        assert result.job_active is True
        assert result.is_enabled is True
        assert result.next_run_time is not None
        assert result.updated_by == "admin"
        assert result.message is None

    @pytest.mark.asyncio
    async def test_get_config_without_db_config(self):
        """无 DB 配置时，使用环境变量默认值且 is_enabled=False。"""
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = None

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None

        service = ScraperScheduleService(mock_repo)

        with (
            patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler),
            patch("src.preference.services.schedule_service.get_settings") as mock_settings,
        ):
            mock_settings.return_value.scraper_interval = 43200
            result = await service.get_schedule_config()

        assert result.interval_seconds == 43200
        assert result.scheduler_running is True
        assert result.job_active is False
        assert result.is_enabled is False

    @pytest.mark.asyncio
    async def test_get_config_scheduler_not_running(self):
        """调度器未运行时，返回 scheduler_running=False。"""
        db_config = _make_config()
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = db_config

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            result = await service.get_schedule_config()

        assert result.scheduler_running is False
        assert result.job_active is False
        assert result.interval_seconds == 600


class TestUpdateInterval:
    """测试更新抓取间隔。"""

    @pytest.mark.asyncio
    async def test_update_interval_with_existing_job(self):
        """调度器有 job 时，reschedule_job。"""
        db_config = _make_config(interval_seconds=1200)
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
            interval_seconds=1200, is_enabled=True, updated_by="admin"
        )
        mock_scheduler.reschedule_job.assert_called_once_with(
            "scraper_job", trigger="interval", seconds=1200
        )
        assert result.interval_seconds == 1200
        assert result.scheduler_running is True

    @pytest.mark.asyncio
    async def test_update_interval_creates_job_when_missing(self):
        """调度器无 job 时，update_interval 应创建 job。"""
        db_config = _make_config(interval_seconds=1200)
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None  # 无 job

        service = ScraperScheduleService(mock_repo)

        with (
            patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler),
            patch("src.scraper.scheduled_job.scheduled_scrape_job"),
        ):
            result = await service.update_interval(1200, "admin")

        mock_scheduler.add_job.assert_called_once()
        assert result.scheduler_running is True

    @pytest.mark.asyncio
    async def test_update_interval_scheduler_not_running(self):
        """调度器未运行时，仍持久化配置。"""
        db_config = _make_config(interval_seconds=1200)
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
        db_config = _make_config(next_run_time=future_time)
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
    async def test_update_next_run_time_creates_job_when_missing(self):
        """调度器无 job 时，update_next_run_time 应创建 job。"""
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        db_config = _make_config(interval_seconds=600, next_run_time=future_time)
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None  # 无 job

        service = ScraperScheduleService(mock_repo)

        with (
            patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler),
            patch("src.scraper.scheduled_job.scheduled_scrape_job"),
        ):
            result = await service.update_next_run_time(future_time, "admin")

        mock_scheduler.add_job.assert_called_once()
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
        db_config = _make_config(next_run_time=future_time)
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None):
            result = await service.update_next_run_time(future_time, "admin")

        mock_repo.upsert_schedule_config.assert_called_once()
        assert result.scheduler_running is False
        assert result.message is not None


class TestEnableSchedule:
    """测试启用调度。"""

    @pytest.mark.asyncio
    async def test_enable_schedule_with_config(self):
        """有 DB 配置时，enable 应创建 job。"""
        db_config = _make_config(is_enabled=False)
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = db_config
        mock_repo.upsert_schedule_config.return_value = _make_config(is_enabled=True)

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None  # 无 job

        service = ScraperScheduleService(mock_repo)

        with (
            patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler),
            patch("src.scraper.scheduled_job.scheduled_scrape_job"),
        ):
            result = await service.enable_schedule("admin")

        mock_scheduler.add_job.assert_called_once()
        assert result.scheduler_running is True

    @pytest.mark.asyncio
    async def test_enable_schedule_without_config_auto_creates(self):
        """无 DB 配置时，enable 应使用默认间隔自动创建配置。"""
        mock_repo = AsyncMock()
        # 第一次 get 返回 None（无配置），upsert 后第二次 get 返回新建配置
        created_config = _make_config(interval_seconds=3600, is_enabled=True)
        mock_repo.get_schedule_config.side_effect = [None, created_config, created_config]

        service = ScraperScheduleService(mock_repo)

        mock_settings = MagicMock()
        mock_settings.scraper_interval = 3600

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=None), \
             patch("src.preference.services.schedule_service.get_settings", return_value=mock_settings):
            result = await service.enable_schedule("admin")

        mock_repo.upsert_schedule_config.assert_called_once_with(
            interval_seconds=3600,
            is_enabled=True,
            updated_by="admin",
        )
        assert result.is_enabled is True

    @pytest.mark.asyncio
    async def test_enable_schedule_already_active(self):
        """job 已存在时，enable 是幂等的。"""
        db_config = _make_config(is_enabled=True)
        mock_repo = AsyncMock()
        mock_repo.get_schedule_config.return_value = db_config
        mock_repo.upsert_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.next_run_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_scheduler.get_job.return_value = mock_job  # job 已存在

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler):
            result = await service.enable_schedule("admin")

        # 不应创建新 job（add_job 不应被调用）
        mock_scheduler.add_job.assert_not_called()
        assert result.scheduler_running is True


class TestDisableSchedule:
    """测试暂停调度。"""

    @pytest.mark.asyncio
    async def test_disable_schedule_removes_job(self):
        """暂停应移除 scraper_job。"""
        db_config = _make_config(is_enabled=False)
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_scheduler.get_job.return_value = mock_job

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler):
            result = await service.disable_schedule("admin")

        mock_scheduler.remove_job.assert_called_once_with("scraper_job")
        mock_repo.upsert_schedule_config.assert_called_once_with(
            is_enabled=False, updated_by="admin"
        )
        assert result.message == "调度已暂停"

    @pytest.mark.asyncio
    async def test_disable_schedule_no_job(self):
        """无 job 时暂停是幂等的。"""
        db_config = _make_config(is_enabled=False)
        mock_repo = AsyncMock()
        mock_repo.upsert_schedule_config.return_value = db_config
        mock_repo.get_schedule_config.return_value = db_config

        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None

        service = ScraperScheduleService(mock_repo)

        with patch("src.preference.services.schedule_service.get_scheduler", return_value=mock_scheduler):
            result = await service.disable_schedule("admin")

        mock_scheduler.remove_job.assert_not_called()
        assert result.message == "调度已暂停"
