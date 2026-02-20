"""drop deduplication tables and columns

移除去重功能：删除 deduplication_groups 表、tweets.deduplication_group_id 列及相关外键和索引。

Revision ID: d1_drop_deduplication
Revises: t4_add_tz_offset
Create Date: 2026-02-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1_drop_deduplication"
down_revision: Union[str, Sequence[str], None] = "t4_add_tz_offset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除去重相关的表和列。"""

    # 1. 删除 tweets 表上的 deduplication_group_id 列
    #    batch_alter_table 在 SQLite 中会重建表，自动处理关联的 FK 约束
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.drop_column("deduplication_group_id")

    # 2. 删除 deduplication_groups 表
    op.drop_table("deduplication_groups")


def downgrade() -> None:
    """重建去重相关的表和列。"""

    # 1. 重建 deduplication_groups 表
    op.create_table(
        "deduplication_groups",
        sa.Column("group_id", sa.String(length=255), nullable=False),
        sa.Column(
            "representative_tweet_id", sa.String(length=255), nullable=False
        ),
        sa.Column("deduplication_type", sa.String(length=20), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("tweet_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("group_id"),
    )

    # 2. 重建 tweets.deduplication_group_id 列
    with op.batch_alter_table("tweets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "deduplication_group_id",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_tweets_deduplication_group_id",
            "deduplication_groups",
            ["deduplication_group_id"],
            ["group_id"],
            ondelete="SET NULL",
        )

    # 3. 重建 deduplication_groups -> tweets FK
    with op.batch_alter_table("deduplication_groups") as batch_op:
        batch_op.create_foreign_key(
            "fk_deduplication_groups_representative_tweet_id",
            "tweets",
            ["representative_tweet_id"],
            ["tweet_id"],
            ondelete="CASCADE",
        )
