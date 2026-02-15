"""add scheduler_execution_log table

新增调度器执行日志表，记录 APScheduler 任务的执行/错误/遗漏事件，
用于调度器可观测性和执行历史追溯。

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-02-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h3i4j5k6l7m8"
down_revision: Union[str, Sequence[str], None] = "g2h3i4j5k6l7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 scheduler_execution_log 表。"""
    op.create_table(
        "scheduler_execution_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(100), nullable=False, comment="APScheduler Job ID"),
        sa.Column("event_type", sa.String(20), nullable=False, comment="事件类型: executed, error, missed"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False, comment="事件发生时间"),
        sa.Column("duration_seconds", sa.Float, nullable=True, comment="执行耗时（秒）"),
        sa.Column("error_type", sa.String(200), nullable=True, comment="异常类型名"),
        sa.Column("error_message", sa.Text, nullable=True, comment="异常信息"),
        sa.Column("next_run_time", sa.DateTime(timezone=True), nullable=True, comment="下次计划运行时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="记录创建时间"),
        comment="调度器执行日志表",
    )
    op.create_index("idx_scheduler_log_job_id", "scheduler_execution_log", ["job_id"])
    op.create_index("idx_scheduler_log_event_type", "scheduler_execution_log", ["event_type"])
    op.create_index("idx_scheduler_log_executed_at", "scheduler_execution_log", ["executed_at"])


def downgrade() -> None:
    """删除 scheduler_execution_log 表。"""
    op.drop_table("scheduler_execution_log")
