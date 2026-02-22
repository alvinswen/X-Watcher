"""add x_user_profiles table

新建 x_user_profiles 表，用于缓存从 TwitterAPI.io 获取的 X 平台用户档案信息。
以 platform_user_id 为主键，与 scraper_follows 表通过该字段关联。

Revision ID: u2_add_x_user_profiles_table
Revises: u1_add_platform_user_id
Create Date: 2026-02-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "u2_add_x_user_profiles_table"
down_revision: Union[str, None] = "u1_add_platform_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "x_user_profiles",
        sa.Column("platform_user_id", sa.String(64), primary_key=True, comment="X 平台永久 user_id"),
        sa.Column("username", sa.String(15), nullable=False, comment="当前用户名（可变）"),
        sa.Column("display_name", sa.String(200), nullable=True, comment="显示名称"),
        sa.Column("is_blue_verified", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否蓝标认证"),
        sa.Column("verified_type", sa.String(50), nullable=True, comment="认证类型"),
        sa.Column("profile_picture", sa.Text(), nullable=True, comment="头像 URL"),
        sa.Column("cover_picture", sa.Text(), nullable=True, comment="封面图 URL"),
        sa.Column("description", sa.Text(), nullable=True, comment="个人简介"),
        sa.Column("location", sa.String(200), nullable=True, comment="位置"),
        sa.Column("followers_count", sa.Integer(), nullable=True, comment="粉丝数"),
        sa.Column("following_count", sa.Integer(), nullable=True, comment="关注数"),
        sa.Column("statuses_count", sa.Integer(), nullable=True, comment="推文总数"),
        sa.Column("favourites_count", sa.Integer(), nullable=True, comment="点赞数"),
        sa.Column("media_count", sa.Integer(), nullable=True, comment="媒体推文数"),
        sa.Column("account_created_at", sa.String(100), nullable=True, comment="账号创建日期（原始字符串）"),
        sa.Column("is_automated", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否自动化账号"),
        sa.Column("possibly_sensitive", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否可能包含敏感内容"),
        sa.Column("pinned_tweet_ids", sa.JSON(), nullable=True, comment="置顶推文 ID 列表"),
        sa.Column("unavailable", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="账号是否不可用"),
        sa.Column("unavailable_reason", sa.String(200), nullable=True, comment="不可用原因"),
        sa.Column("raw_json", sa.Text(), nullable=True, comment="完整 API 响应 JSON"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, comment="数据获取时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="记录创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="记录更新时间"),
    )

    op.create_index("idx_x_user_profiles_username", "x_user_profiles", ["username"])
    op.create_index("idx_x_user_profiles_fetched_at", "x_user_profiles", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("idx_x_user_profiles_fetched_at", table_name="x_user_profiles")
    op.drop_index("idx_x_user_profiles_username", table_name="x_user_profiles")
    op.drop_table("x_user_profiles")
