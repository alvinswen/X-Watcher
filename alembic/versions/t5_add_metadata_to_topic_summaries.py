"""add metadata to topic_summaries

在主题摘要表中新增 metadata JSON 列，用于存放结构化的"观点 ↔ 出处"映射、
综述时间区间(review_window)等机器可读字段。content 仍存人读 Markdown，
两者并存、互不覆盖。

Revision ID: t5_add_metadata
Revises: t4_add_tz_offset
Create Date: 2026-05-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t5_add_metadata"
down_revision: Union[str, None] = "t4_add_tz_offset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 metadata JSON 列，默认为空对象。"""
    with op.batch_alter_table("topic_summaries") as batch_op:
        batch_op.add_column(
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
                comment="结构化扩展字段：observations、review_window、review_kind 等",
            )
        )


def downgrade() -> None:
    """删除 metadata JSON 列。"""
    with op.batch_alter_table("topic_summaries") as batch_op:
        batch_op.drop_column("metadata_json")
