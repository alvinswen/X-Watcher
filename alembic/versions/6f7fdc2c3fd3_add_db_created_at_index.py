"""add_db_created_at_index

为推文入库时间字段添加索引，优化 Feed API 时间区间查询性能。

Revision ID: 6f7fdc2c3fd3
Revises: 7c5ed982a2eb
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "6f7fdc2c3fd3"
down_revision: Union[str, None] = "7c5ed982a2eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 db_created_at 索引。"""
    op.create_index("ix_tweets_db_created_at", "tweets", ["db_created_at"])


def downgrade() -> None:
    """删除 db_created_at 索引。"""
    op.drop_index("ix_tweets_db_created_at", table_name="tweets")
