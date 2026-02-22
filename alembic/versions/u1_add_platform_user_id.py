"""add platform_user_id to scraper_follows and author_user_id to tweets

为 scraper_follows 表添加 platform_user_id 列（X 平台永久不变的数值型用户 ID），
为 tweets 表添加 author_user_id 列，用于稳定标识账号、检测改名。

Revision ID: u1_add_platform_user_id
Revises: p2_add_user_id_to_topics
Create Date: 2026-02-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "u1_add_platform_user_id"
down_revision: Union[str, None] = "p2_add_user_id_to_topics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 platform_user_id 和 author_user_id 列。"""
    # scraper_follows 表：新增 platform_user_id
    with op.batch_alter_table("scraper_follows") as batch_op:
        batch_op.add_column(
            sa.Column("platform_user_id", sa.String(64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_scraper_follows_platform_user_id", ["platform_user_id"]
        )
        batch_op.create_index(
            "idx_scraper_follows_platform_user_id", ["platform_user_id"]
        )

    # tweets 表：新增 author_user_id
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.add_column(
            sa.Column("author_user_id", sa.String(64), nullable=True)
        )
        batch_op.create_index("idx_tweets_author_user_id", ["author_user_id"])


def downgrade() -> None:
    """移除 platform_user_id 和 author_user_id 列。"""
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.drop_index("idx_tweets_author_user_id")
        batch_op.drop_column("author_user_id")

    with op.batch_alter_table("scraper_follows") as batch_op:
        batch_op.drop_index("idx_scraper_follows_platform_user_id")
        batch_op.drop_constraint(
            "uq_scraper_follows_platform_user_id", type_="unique"
        )
        batch_op.drop_column("platform_user_id")
