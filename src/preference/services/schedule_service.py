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

    def _ensure_job_exists(
        self, scheduler, interval_seconds: int, next_run_time=None
    ) -> bool:
        """确保 scraper_job 存在，不存在则创建。

        Returns:
            bool: True 表示新创建了 job，False 表示 job 已存在
        """
        job = scheduler.get_job("scraper_job")
        if job is None:
            from src.scraper.scheduled_job import scheduled_scrape_job

            scheduler.add_job(
                scheduled_scrape_job,
                "interval",
                seconds=interval_seconds,
                id="scraper_job",
                name="定时抓取推文",
                max_instances=1,
                replace_existing=True,
                next_run_time=next_run_time or datetime.now(),
            )
            logger.info(f"调度任务已创建: 间隔 {interval_seconds} 秒")
            return True
        return False

    def _remove_job_if_exists(self, scheduler) -> bool:
        """移除 scraper_job（如果存在）。

        Returns:
            bool: True 表示移除了 job，False 表示 job 不存在
        """
        job = scheduler.get_job("scraper_job")
        if job is not None:
            scheduler.remove_job("scraper_job")
            return True
        return False

    async def get_schedule_config(self) -> ScheduleConfigResponse:
        """获取当前调度配置。

        合并 DB 配置 + 调度器运行状态 + 环境变量默认值。
        """
        db_config = await self._repository.get_schedule_config()
        scheduler = get_scheduler()
        scheduler_running = scheduler is not None

        if db_config:
            interval_seconds = db_config.interval_seconds
            is_enabled = db_config.is_enabled
            updated_at = db_config.updated_at
            updated_by = db_config.updated_by
        else:
            settings = get_settings()
            interval_seconds = settings.scraper_interval
            is_enabled = False
            updated_at = None
            updated_by = None

        # 从调度器获取实际的 next_run_time
        next_run_time = None
        job_active = False
        if db_config and db_config.next_run_time:
            next_run_time = db_config.next_run_time
        if scheduler_running:
            job = scheduler.get_job("scraper_job")
            if job:
                job_active = True
                if job.next_run_time:
                    next_run_time = job.next_run_time

        return ScheduleConfigResponse(
            interval_seconds=interval_seconds,
            next_run_time=next_run_time,
            scheduler_running=scheduler_running,
            job_active=job_active,
            is_enabled=is_enabled,
            updated_at=updated_at,
            updated_by=updated_by,
        )

    async def update_interval(
        self, interval_seconds: int, updated_by: str
    ) -> ScheduleConfigResponse:
        """更新抓取间隔。

        隐式启用调度：设置间隔意味着管理员希望调度处于活跃状态。
        """
        await self._repository.upsert_schedule_config(
            interval_seconds=interval_seconds,
            is_enabled=True,
            updated_by=updated_by,
        )

        scheduler = get_scheduler()
        scheduler_running = scheduler is not None
        message = None

        if scheduler_running:
            job = scheduler.get_job("scraper_job")
            if job:
                scheduler.reschedule_job(
                    "scraper_job", trigger="interval", seconds=interval_seconds
                )
            else:
                self._ensure_job_exists(scheduler, interval_seconds)
            logger.info(f"调度间隔已更新为 {interval_seconds} 秒, by {updated_by}")
        else:
            message = "调度器当前未运行，配置已保存，将在启用后生效"
            logger.info(f"调度间隔已保存（调度器未运行）: {interval_seconds} 秒, by {updated_by}")

        return await self._build_response(scheduler, scheduler_running, message)

    async def update_next_run_time(
        self, next_run_time: datetime, updated_by: str
    ) -> ScheduleConfigResponse:
        """设置下次触发时间。

        隐式启用调度：设置触发时间意味着管理员希望调度处于活跃状态。
        """
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
            next_run_time=next_run_time,
            is_enabled=True,
            updated_by=updated_by,
        )

        scheduler = get_scheduler()
        scheduler_running = scheduler is not None
        message = None

        if scheduler_running:
            job = scheduler.get_job("scraper_job")
            if job:
                scheduler.modify_job("scraper_job", next_run_time=next_run_time)
            else:
                # 需要 interval 来创建 job，从 DB 读取
                db_config = await self._repository.get_schedule_config()
                interval = db_config.interval_seconds if db_config else 43200
                self._ensure_job_exists(scheduler, interval, next_run_time)
            logger.info(f"下次触发时间已设置为 {next_run_time}, by {updated_by}")
        else:
            message = "调度器当前未运行，配置已保存，将在启用后生效"
            logger.info(f"下次触发时间已保存（调度器未运行）: {next_run_time}, by {updated_by}")

        return await self._build_response(scheduler, scheduler_running, message)

    async def enable_schedule(self, updated_by: str) -> ScheduleConfigResponse:
        """启用调度。

        从 DB 恢复配置并创建 scraper_job。
        如果 DB 无配置，返回 422 提示先设置间隔。
        """
        db_config = await self._repository.get_schedule_config()

        if db_config is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="尚未配置调度参数，请先设置抓取间隔",
            )

        await self._repository.upsert_schedule_config(
            is_enabled=True, updated_by=updated_by
        )

        scheduler = get_scheduler()
        scheduler_running = scheduler is not None
        message = None

        if scheduler_running:
            self._ensure_job_exists(
                scheduler, db_config.interval_seconds, db_config.next_run_time
            )
            logger.info(f"调度已启用, by {updated_by}")
        else:
            message = "调度器当前未运行，配置已保存，将在启用后生效"

        return await self._build_response(scheduler, scheduler_running, message)

    async def disable_schedule(self, updated_by: str) -> ScheduleConfigResponse:
        """暂停调度。

        移除 scraper_job 但保留 DB 中的调度配置。
        """
        await self._repository.upsert_schedule_config(
            is_enabled=False, updated_by=updated_by
        )

        scheduler = get_scheduler()
        scheduler_running = scheduler is not None

        if scheduler_running:
            if self._remove_job_if_exists(scheduler):
                logger.info(f"调度任务已暂停, by {updated_by}")

        return await self._build_response(scheduler, scheduler_running, "调度已暂停")

    async def _build_response(
        self, scheduler, scheduler_running: bool, message: str | None
    ) -> ScheduleConfigResponse:
        """构建统一的配置响应。"""
        db_config = await self._repository.get_schedule_config()

        next_run_time = None
        job_active = False
        is_enabled = False

        if db_config:
            is_enabled = db_config.is_enabled
            if db_config.next_run_time:
                next_run_time = db_config.next_run_time

        if scheduler_running and scheduler:
            job = scheduler.get_job("scraper_job")
            if job:
                job_active = True
                if job.next_run_time:
                    next_run_time = job.next_run_time

        return ScheduleConfigResponse(
            interval_seconds=db_config.interval_seconds if db_config else 43200,
            next_run_time=next_run_time,
            scheduler_running=scheduler_running,
            job_active=job_active,
            is_enabled=is_enabled,
            updated_at=db_config.updated_at if db_config else None,
            updated_by=db_config.updated_by if db_config else None,
            message=message,
        )
