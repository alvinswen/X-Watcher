"""add manual_limit to scraper_follows

为 scraper_follows 表新增 manual_limit 字段，
允许管理员为指定账号手动配置推文抓取数量。

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-02-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i4j5k6l7m8n9"
down_revision: Union[str, None] = "h3i4j5k6l7m8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scraper_follows",
        sa.Column("manual_limit", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scraper_follows", "manual_limit")
