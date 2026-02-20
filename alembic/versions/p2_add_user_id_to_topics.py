"""add user_id to topics

为 topics 表添加 user_id 列，支持多用户主题所有权。
移除 name 列的全局唯一约束，改为 (user_id, name) 复合唯一约束。

Revision ID: p2_add_user_id_to_topics
Revises: p1_drop_twitter_follows
Create Date: 2026-02-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p2_add_user_id_to_topics"
down_revision: Union[str, None] = "p1_drop_twitter_follows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 为 SQLite 批处理模式提供约束命名规范（帮助识别未命名的约束）
_naming_convention = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def upgrade() -> None:
    """添加 user_id 列、索引，并将唯一约束从 name 改为 (user_id, name)。"""
    with op.batch_alter_table("topics", naming_convention=_naming_convention) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_topics_user_id", "users", ["user_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_topics_user_id", ["user_id"])
        batch_op.drop_constraint("uq_topics_name", type_="unique")
        batch_op.create_unique_constraint("uq_topics_user_id_name", ["user_id", "name"])


def downgrade() -> None:
    """移除 user_id 列，恢复 name 列的全局唯一约束。"""
    with op.batch_alter_table("topics", naming_convention=_naming_convention) as batch_op:
        batch_op.drop_constraint("uq_topics_user_id_name", type_="unique")
        batch_op.create_unique_constraint("uq_topics_name", ["name"])
        batch_op.drop_index("ix_topics_user_id")
        batch_op.drop_constraint("fk_topics_user_id", type_="foreignkey")
        batch_op.drop_column("user_id")
