"""add backfill fields to scraper_follows

为 scraper_follows 表新增 backfill_status 和 backfill_completed_at 字段，
支持新用户全量回溯功能。已有记录默认设为 skipped（不自动回溯，可手动触发）。

Revision ID: b1_add_backfill_fields
Revises: u2_add_x_user_profiles_table
Create Date: 2026-02-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b1_add_backfill_fields"
down_revision: Union[str, None] = "u2_add_x_user_profiles_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 backfill_status 列，先设默认值为 skipped（已有记录不自动回溯）
    op.add_column(
        "scraper_follows",
        sa.Column(
            "backfill_status",
            sa.String(20),
            nullable=False,
            server_default="skipped",
            comment="回溯状态: pending/running/completed/skipped",
        ),
    )
    op.add_column(
        "scraper_follows",
        sa.Column(
            "backfill_completed_at",
            sa.DateTime(),
            nullable=True,
            comment="回溯完成时间",
        ),
    )
    op.create_index(
        "idx_scraper_follows_backfill_status",
        "scraper_follows",
        ["backfill_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_scraper_follows_backfill_status", table_name="scraper_follows")
    op.drop_column("scraper_follows", "backfill_completed_at")
    op.drop_column("scraper_follows", "backfill_status")
