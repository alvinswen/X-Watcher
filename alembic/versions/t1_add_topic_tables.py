"""add topic tables

创建主题管理相关的 4 张表：topics, topic_accounts, topic_summary_tasks, topic_summaries。

Revision ID: t1_add_topic_tables
Revises: i4j5k6l7m8n9
Create Date: 2026-02-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "t1_add_topic_tables"
down_revision: Union[str, None] = "i4j5k6l7m8n9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 创建 topics 表
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # 创建 topic_accounts 表
    op.create_table(
        "topic_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", "username", name="uq_topic_accounts_topic_username"),
    )
    op.create_index("ix_topic_accounts_topic_id", "topic_accounts", ["topic_id"], unique=False)

    # 创建 topic_summary_tasks 表
    op.create_table(
        "topic_summary_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("time_span_hours", sa.Integer(), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("custom_prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topic_summary_tasks_topic_id", "topic_summary_tasks", ["topic_id"], unique=False)
    op.create_index("ix_topic_summary_tasks_status", "topic_summary_tasks", ["status"], unique=False)

    # 创建 topic_summaries 表
    op.create_table(
        "topic_summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("llm_provider", sa.String(length=50), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("tweet_count", sa.Integer(), nullable=False),
        sa.Column("account_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["topic_summary_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""

    # 按依赖顺序反向删除
    op.drop_table("topic_summaries")
    op.drop_index("ix_topic_summary_tasks_status", table_name="topic_summary_tasks")
    op.drop_index("ix_topic_summary_tasks_topic_id", table_name="topic_summary_tasks")
    op.drop_table("topic_summary_tasks")
    op.drop_index("ix_topic_accounts_topic_id", table_name="topic_accounts")
    op.drop_table("topic_accounts")
    op.drop_table("topics")
