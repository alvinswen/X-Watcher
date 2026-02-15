"""调度器执行历史 API 路由。

提供调度器执行日志查询端点，用于管理员监控定时任务运行状态。
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from src.database.async_session import get_db_session
from src.scraper.domain.scheduler_log import SchedulerEventType
from src.scraper.infrastructure.scheduler_log_repository import (
    SchedulerExecutionLogRepository,
)
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/scheduler", tags=["scheduler"])


@router.get("/history")
async def get_scheduler_history(
    limit: int = Query(default=50, ge=1, le=200, description="返回记录数"),
    event_type: str | None = Query(
        default=None, description="事件类型过滤: executed, error, missed"
    ),
    since: datetime | None = Query(
        default=None, description="起始时间 (ISO 8601)"
    ),
    session=Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
) -> list[dict]:
    """查询调度器执行历史。

    返回最近的调度器执行/错误/遗漏事件日志。
    """
    repo = SchedulerExecutionLogRepository(session)

    et = None
    if event_type is not None:
        et = SchedulerEventType(event_type)

    logs = await repo.get_recent_logs(limit=limit, event_type=et, since=since)

    return [
        {
            "id": log.id,
            "job_id": log.job_id,
            "event_type": log.event_type.value,
            "executed_at": log.executed_at.isoformat(),
            "duration_seconds": log.duration_seconds,
            "error_type": log.error_type,
            "error_message": log.error_message,
            "next_run_time": (
                log.next_run_time.isoformat() if log.next_run_time else None
            ),
        }
        for log in logs
    ]
