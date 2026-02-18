"""nullable topic_id in summary_tasks

支持"全部账号"摘要任务：topic_id 允许为 NULL，表示基于所有活跃账号生成摘要。
同时将 ondelete 从 CASCADE 改为 SET NULL，避免删除主题时级联删除全部账号的任务。

Revision ID: t2_nullable_topic_id
Revises: t1_add_topic_tables
Create Date: 2026-02-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t2_nullable_topic_id"
down_revision: Union[str, None] = "t1_add_topic_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# SQLite 匿名 FK naming convention，用于 batch 模式识别约束
naming_convention = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    """将 topic_summary_tasks.topic_id 改为可空，ondelete 改为 SET NULL。"""
    with op.batch_alter_table(
        "topic_summary_tasks", naming_convention=naming_convention
    ) as batch_op:
        batch_op.alter_column("topic_id", existing_type=sa.Integer(), nullable=True)
        batch_op.drop_constraint(
            "fk_topic_summary_tasks_topic_id_topics", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_topic_summary_tasks_topic_id_topics",
            "topics",
            ["topic_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """将 topic_summary_tasks.topic_id 恢复为非空，ondelete 恢复为 CASCADE。"""
    # 先删除 topic_id 为 NULL 的行（无法设为 NOT NULL）
    op.execute("DELETE FROM topic_summary_tasks WHERE topic_id IS NULL")
    with op.batch_alter_table(
        "topic_summary_tasks", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_topic_summary_tasks_topic_id_topics", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_topic_summary_tasks_topic_id_topics",
            "topics",
            ["topic_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.alter_column("topic_id", existing_type=sa.Integer(), nullable=False)
