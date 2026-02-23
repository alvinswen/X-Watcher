"""add articles table

新建 articles 表，用于存储 X 平台长文章内容。
以 tweet_id 为主键，独立存储避免 tweets 表膨胀。

Revision ID: a1_add_articles_table
Revises: b2_add_brief_intro_to_scraper_follows
Create Date: 2026-02-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1_add_articles_table"
down_revision: Union[str, None] = "b2_add_brief_intro_to_scraper_follows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("tweet_id", sa.String(255), primary_key=True, comment="关联推文 ID"),
        sa.Column("title", sa.Text(), nullable=True, comment="文章标题"),
        sa.Column("preview_text", sa.Text(), nullable=True, comment="预览文本"),
        sa.Column("cover_image_url", sa.Text(), nullable=True, comment="封面图片 URL"),
        sa.Column("content", sa.Text(), nullable=True, comment="文章正文（纯文本）"),
        sa.Column("content_html", sa.Text(), nullable=True, comment="文章正文（HTML）"),
        sa.Column("author_username", sa.String(255), nullable=True, comment="作者用户名"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True, comment="数据获取时间"),
        sa.Column(
            "db_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="数据库记录创建时间",
        ),
        comment="X 平台长文章数据表",
    )


def downgrade() -> None:
    op.drop_table("articles")
