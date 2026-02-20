"""drop twitter_follows table

移除 per-user follows 功能，删除 twitter_follows 表。

Revision ID: p1_drop_twitter_follows
Revises: d1_drop_deduplication
Create Date: 2026-02-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p1_drop_twitter_follows"
down_revision: Union[str, None] = "d1_drop_deduplication"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 twitter_follows 表。"""
    op.drop_table("twitter_follows")


def downgrade() -> None:
    """重建 twitter_follows 表。"""
    op.create_table(
        "twitter_follows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(15), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "username", name="uq_twitter_follows_user_username"),
    )
    op.create_index("idx_twitter_follows_user_id", "twitter_follows", ["user_id"])
    op.create_index("idx_twitter_follows_username", "twitter_follows", ["username"])
