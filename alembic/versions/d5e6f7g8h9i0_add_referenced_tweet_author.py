"""add_referenced_tweet_author_username

为推文表新增 referenced_tweet_author_username 字段，
用于存储被引用/转发推文的原作者用户名。

Revision ID: d5e6f7g8h9i0
Revises: 492f70102988
Create Date: 2026-02-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7g8h9i0"
down_revision: Union[str, None] = "492f70102988"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增被引用推文原作者用户名字段。"""
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "referenced_tweet_author_username",
                sa.String(255),
                nullable=True,
                comment="被引用/转发推文的原作者用户名",
            )
        )


def downgrade() -> None:
    """移除被引用推文原作者用户名字段。"""
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.drop_column("referenced_tweet_author_username")
