"""add brief_intro to scraper_follows

为 scraper_follows 表新增 brief_intro 字段，用于存储极简介绍（≤10汉字）。
支持 LLM 自动生成 + 人工编辑，在主题摘要中使用。

Revision ID: b2_add_brief_intro_to_scraper_follows
Revises: u2_add_x_user_profiles_table
Create Date: 2026-02-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b2_add_brief_intro_to_scraper_follows"
down_revision: Union[str, None] = "u2_add_x_user_profiles_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scraper_follows",
        sa.Column("brief_intro", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scraper_follows", "brief_intro")
