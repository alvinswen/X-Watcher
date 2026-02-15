"""APScheduler 事件监听器。

监听调度器的 job executed / error / missed 事件，
记录结构化日志并持久化到数据库。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
)

from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog
from src.scraper.infrastructure.scheduler_log_repository import (
    SchedulerExecutionLogSyncWriter,
)

logger = logging.getLogger(__name__)


def _get_next_run_time(job_id: str) -> datetime | None:
    """从调度器获取 job 的下次运行时间。"""
    try:
        from src.scheduler_accessor import get_scheduler

        scheduler = get_scheduler()
        if scheduler is None:
            return None
        job = scheduler.get_job(job_id)
        if job is None:
            return None
        return job.next_run_time
    except Exception:
        return None


def _update_prometheus_metrics(
    event_type: SchedulerEventType, job_id: str, duration: float | None
) -> None:
    """更新 Prometheus 指标。"""
    try:
        from src.config import get_settings

        settings = get_settings()
        if not settings.prometheus_enabled:
            return

        from src.monitoring import metrics

        if event_type == SchedulerEventType.EXECUTED:
            metrics.scheduler_job_executed_total.labels(job_id=job_id).inc()
            if duration is not None:
                metrics.scheduler_job_duration_seconds.labels(
                    job_id=job_id
                ).set(duration)
        elif event_type == SchedulerEventType.ERROR:
            metrics.scheduler_job_error_total.labels(job_id=job_id).inc()
            if duration is not None:
                metrics.scheduler_job_duration_seconds.labels(
                    job_id=job_id
                ).set(duration)
        elif event_type == SchedulerEventType.MISSED:
            metrics.scheduler_job_missed_total.labels(job_id=job_id).inc()
    except Exception:
        pass  # 静默失败，避免指标更新影响业务逻辑


def _calc_duration(event: Any) -> float | None:
    """从 APScheduler 事件计算执行耗时。"""
    if hasattr(event, "scheduled_run_time") and event.scheduled_run_time:
        scheduled = event.scheduled_run_time
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - scheduled).total_seconds()
    return None


def scheduler_event_listener(event: Any) -> None:
    """APScheduler 事件监听回调。

    处理 EVENT_JOB_EXECUTED、EVENT_JOB_ERROR、EVENT_JOB_MISSED 三种事件。
    在 APScheduler 的线程中同步执行。

    Args:
        event: APScheduler JobEvent / JobExecutionEvent 实例
    """
    job_id = event.job_id
    now = datetime.now(timezone.utc)
    next_run = _get_next_run_time(job_id)

    if event.code == EVENT_JOB_EXECUTED:
        duration_secs = _calc_duration(event)

        logger.info(
            "调度任务执行成功",
            extra={
                "event": "scheduler_job_executed",
                "job_id": job_id,
                "duration_seconds": duration_secs,
                "next_run_time": (
                    next_run.isoformat() if next_run else None
                ),
            },
        )

        log_entry = SchedulerExecutionLog(
            job_id=job_id,
            event_type=SchedulerEventType.EXECUTED,
            executed_at=now,
            duration_seconds=duration_secs,
            next_run_time=next_run,
        )
        SchedulerExecutionLogSyncWriter.write_log(log_entry)
        _update_prometheus_metrics(
            SchedulerEventType.EXECUTED, job_id, duration_secs
        )

    elif event.code == EVENT_JOB_ERROR:
        duration_secs = _calc_duration(event)

        exception = event.exception
        error_type_name = (
            type(exception).__name__ if exception else "Unknown"
        )
        error_msg = str(exception) if exception else None
        if error_msg is None and event.traceback:
            error_msg = str(event.traceback)

        logger.error(
            "调度任务执行失败",
            extra={
                "event": "scheduler_job_error",
                "job_id": job_id,
                "error_type": error_type_name,
                "error_message": error_msg,
                "duration_seconds": duration_secs,
                "next_run_time": (
                    next_run.isoformat() if next_run else None
                ),
            },
        )

        log_entry = SchedulerExecutionLog(
            job_id=job_id,
            event_type=SchedulerEventType.ERROR,
            executed_at=now,
            duration_seconds=duration_secs,
            error_type=error_type_name,
            error_message=(
                error_msg[:2000] if error_msg else None
            ),
            next_run_time=next_run,
        )
        SchedulerExecutionLogSyncWriter.write_log(log_entry)
        _update_prometheus_metrics(
            SchedulerEventType.ERROR, job_id, duration_secs
        )

    elif event.code == EVENT_JOB_MISSED:
        scheduled_time = (
            event.scheduled_run_time
            if hasattr(event, "scheduled_run_time")
            else None
        )

        logger.warning(
            "调度任务错过执行",
            extra={
                "event": "scheduler_job_missed",
                "job_id": job_id,
                "scheduled_run_time": (
                    scheduled_time.isoformat() if scheduled_time else None
                ),
                "next_run_time": (
                    next_run.isoformat() if next_run else None
                ),
            },
        )

        log_entry = SchedulerExecutionLog(
            job_id=job_id,
            event_type=SchedulerEventType.MISSED,
            executed_at=now,
            next_run_time=next_run,
        )
        SchedulerExecutionLogSyncWriter.write_log(log_entry)
        _update_prometheus_metrics(
            SchedulerEventType.MISSED, job_id, None
        )
