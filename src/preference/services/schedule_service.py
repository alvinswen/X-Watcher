"""ScraperScheduleService - 调度配置服务。

协调调度配置的业务逻辑：验证、持久化、调度器操作。
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, status

from src.config import get_settings
from src.preference.api.schemas import ScheduleConfigResponse
from src.preference.infrastructure.schedule_repository import ScraperScheduleRepository
from src.scheduler_accessor import get_scheduler

logger = logging.getLogger(__name__)


class ScraperScheduleService:
    """调度配置服务。"""

    def __init__(self, repository: ScraperScheduleRepository) -> None:
        self._repository = repository

    async def get_schedule_config(self) -> ScheduleConfigResponse:
        """获取当前调度配置。

        合并 DB 配置 + 调度器运行状态 + 环境变量默认值。
        """
        db_config = await self._repository.get_schedule_config()
        scheduler = get_scheduler()
        scheduler_running = scheduler is not None

        if db_config:
            interval_seconds = db_config.interval_seconds
            updated_at = db_config.updated_at
            updated_by = db_config.updated_by
        else:
            settings = get_settings()
            interval_seconds = settings.scraper_interval
            updated_at = None
            updated_by = None

        # 从调度器获取实际的 next_run_time
        next_run_time = None
        if db_config and db_config.next_run_time:
            next_run_time = db_config.next_run_time
        if scheduler_running:
            job = scheduler.get_job("scraper_job")
            if job and job.next_run_time:
                next_run_time = job.next_run_time

        return ScheduleConfigResponse(
            interval_seconds=interval_seconds,
            next_run_time=next_run_time,
            scheduler_running=scheduler_running,
            updated_at=updated_at,
            updated_by=updated_by,
        )

    async def update_interval(
        self, interval_seconds: int, updated_by: str
    ) -> ScheduleConfigResponse:
        """更新抓取间隔。"""
        await self._repository.upsert_schedule_config(
            interval_seconds=interval_seconds, updated_by=updated_by
        )

        scheduler = get_scheduler()
        scheduler_running = scheduler is not None
        message = None

        if scheduler_running:
            scheduler.reschedule_job(
                "scraper_job", trigger="interval", seconds=interval_seconds
            )
            logger.info(f"调度间隔已更新为 {interval_seconds} 秒, by {updated_by}")
        else:
            message = "调度器当前未运行，配置已保存，将在启用后生效"
            logger.info(f"调度间隔已保存（调度器未运行）: {interval_seconds} 秒, by {updated_by}")

        return await self._build_response(scheduler, scheduler_running, message)

    async def update_next_run_time(
        self, next_run_time: datetime, updated_by: str
    ) -> ScheduleConfigResponse:
        """设置下次触发时间。"""
        now = datetime.now(timezone.utc)

        # 确保 next_run_time 有时区信息
        if next_run_time.tzinfo is None:
            next_run_time = next_run_time.replace(tzinfo=timezone.utc)

        # 验证：未来时间（-30s 容差）
        if next_run_time < now - timedelta(seconds=30):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="下次触发时间必须为未来时间",
            )

        # 验证：不超过 30 天
        if next_run_time > now + timedelta(days=30):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="下次触发时间不能超过 30 天后",
            )

        await self._repository.upsert_schedule_config(
            next_run_time=next_run_time, updated_by=updated_by
        )

        scheduler = get_scheduler()
        scheduler_running = scheduler is not None
        message = None

        if scheduler_running:
            scheduler.modify_job("scraper_job", next_run_time=next_run_time)
            logger.info(f"下次触发时间已设置为 {next_run_time}, by {updated_by}")
        else:
            message = "调度器当前未运行，配置已保存，将在启用后生效"
            logger.info(f"下次触发时间已保存（调度器未运行）: {next_run_time}, by {updated_by}")

        return await self._build_response(scheduler, scheduler_running, message)

    async def _build_response(
        self, scheduler, scheduler_running: bool, message: str | None
    ) -> ScheduleConfigResponse:
        """构建统一的配置响应。"""
        db_config = await self._repository.get_schedule_config()

        next_run_time = None
        if db_config and db_config.next_run_time:
            next_run_time = db_config.next_run_time
        if scheduler_running and scheduler:
            job = scheduler.get_job("scraper_job")
            if job and job.next_run_time:
                next_run_time = job.next_run_time

        return ScheduleConfigResponse(
            interval_seconds=db_config.interval_seconds if db_config else 43200,
            next_run_time=next_run_time,
            scheduler_running=scheduler_running,
            updated_at=db_config.updated_at if db_config else None,
            updated_by=db_config.updated_by if db_config else None,
            message=message,
        )
