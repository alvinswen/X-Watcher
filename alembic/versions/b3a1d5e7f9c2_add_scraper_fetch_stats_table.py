"""add_scraper_fetch_stats_table

新增抓取统计表，记录每个用户的历史抓取数据，用于动态计算 API limit。

Revision ID: b3a1d5e7f9c2
Revises: 6f7fdc2c3fd3
Create Date: 2026-02-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3a1d5e7f9c2"
down_revision: Union[str, None] = "6f7fdc2c3fd3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 scraper_fetch_stats 表。"""
    op.create_table(
        "scraper_fetch_stats",
        sa.Column("username", sa.String(255), primary_key=True, comment="Twitter 用户名"),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=False, comment="上次抓取时间"),
        sa.Column("last_fetched_count", sa.Integer, nullable=False, server_default="0", comment="上次 API 返回的推文数"),
        sa.Column("last_new_count", sa.Integer, nullable=False, server_default="0", comment="上次新增的推文数"),
        sa.Column("total_fetches", sa.Integer, nullable=False, server_default="0", comment="总抓取次数"),
        sa.Column("avg_new_rate", sa.Float, nullable=False, server_default="1.0", comment="EMA 平滑的新推文率 (0-1)"),
        sa.Column("consecutive_empty_fetches", sa.Integer, nullable=False, server_default="0", comment="连续 0 新推文次数"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="记录创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="记录更新时间"),
        comment="抓取统计表",
    )


def downgrade() -> None:
    """删除 scraper_fetch_stats 表。"""
    op.drop_table("scraper_fetch_stats")
