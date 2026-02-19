"""add tz_offset to topic_summary_tasks

在摘要任务表中新增 tz_offset 列，记录创建任务时用户的时区偏移。
用于生成精确的覆盖时段描述（如 UTC+8）。

Revision ID: t4_add_tz_offset
Revises: t3_materialize_all_accounts
Create Date: 2026-02-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t4_add_tz_offset"
down_revision: Union[str, None] = "t3_materialize_all_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 tz_offset 列，默认值 0（UTC）。"""
    with op.batch_alter_table("topic_summary_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("tz_offset", sa.Integer(), nullable=False, server_default="0", comment="用户时区偏移（分钟）")
        )


def downgrade() -> None:
    """删除 tz_offset 列。"""
    with op.batch_alter_table("topic_summary_tasks") as batch_op:
        batch_op.drop_column("tz_offset")
