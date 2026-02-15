"""调度器执行日志 ORM 模型。

定义 scheduler_execution_log 表的 SQLAlchemy ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models import Base


class SchedulerExecutionLogOrm(Base):
    """调度器执行日志 ORM 模型。

    对应 scheduler_execution_log 表，记录 APScheduler 的执行/错误/遗漏事件。
    """

    __tablename__ = "scheduler_execution_log"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    job_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="APScheduler Job ID"
    )
    event_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="事件类型: executed, error, missed"
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="事件发生时间",
    )
    duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="执行耗时（秒）"
    )
    error_type: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="异常类型名"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="异常信息"
    )
    next_run_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="下次计划运行时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="记录创建时间",
    )

    __table_args__ = (
        Index("idx_scheduler_log_job_id", "job_id"),
        Index("idx_scheduler_log_event_type", "event_type"),
        Index("idx_scheduler_log_executed_at", "executed_at"),
        {"comment": "调度器执行日志表"},
    )

    def to_domain(self) -> "SchedulerExecutionLog":
        """转换为领域模型。"""
        from src.scraper.domain.scheduler_log import (
            SchedulerEventType,
            SchedulerExecutionLog,
        )

        return SchedulerExecutionLog(
            id=self.id,
            job_id=self.job_id,
            event_type=SchedulerEventType(self.event_type),
            executed_at=self.executed_at,
            duration_seconds=self.duration_seconds,
            error_type=self.error_type,
            error_message=self.error_message,
            next_run_time=self.next_run_time,
        )

    @classmethod
    def from_domain(cls, log: "SchedulerExecutionLog") -> "SchedulerExecutionLogOrm":
        """从领域模型创建 ORM 实例。"""
        return cls(
            job_id=log.job_id,
            event_type=log.event_type.value,
            executed_at=log.executed_at,
            duration_seconds=log.duration_seconds,
            error_type=log.error_type,
            error_message=log.error_message,
            next_run_time=log.next_run_time,
        )
