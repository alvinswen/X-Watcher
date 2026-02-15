"""调度器执行日志领域模型。

记录 APScheduler 的 job 执行/错误/遗漏事件。
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SchedulerEventType(str, Enum):
    """调度器事件类型。"""

    EXECUTED = "executed"
    ERROR = "error"
    MISSED = "missed"


class SchedulerExecutionLog(BaseModel):
    """调度器执行日志。"""

    id: int | None = None
    job_id: str = Field(..., description="APScheduler Job ID")
    event_type: SchedulerEventType = Field(..., description="事件类型")
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="事件发生时间",
    )
    duration_seconds: float | None = Field(
        default=None, ge=0, description="执行耗时（秒）"
    )
    error_type: str | None = Field(default=None, description="异常类型名")
    error_message: str | None = Field(default=None, description="异常信息")
    next_run_time: datetime | None = Field(
        default=None, description="下次计划运行时间"
    )
