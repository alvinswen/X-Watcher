"""add_referenced_tweet_fields

为推文表新增 referenced_tweet_text 和 referenced_tweet_media 字段，
用于存储被引用/转发推文的完整文本和媒体附件。

Revision ID: c4d5e6f7g8h9
Revises: b3a1d5e7f9c2
Create Date: 2026-02-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7g8h9"
down_revision: Union[str, None] = "b3a1d5e7f9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增被引用推文内容字段。"""
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "referenced_tweet_text",
                sa.Text(),
                nullable=True,
                comment="被引用/转发推文的完整文本",
            )
        )
        batch_op.add_column(
            sa.Column(
                "referenced_tweet_media",
                sa.JSON(),
                nullable=True,
                comment="被引用/转发推文的媒体附件 JSON",
            )
        )


def downgrade() -> None:
    """移除被引用推文内容字段。"""
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.drop_column("referenced_tweet_media")
        batch_op.drop_column("referenced_tweet_text")
