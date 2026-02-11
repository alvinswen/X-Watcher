"""add_tweets_and_summary_tables

Revision ID: e69b6de02222
Revises: 956cd4f9c8eb
Create Date: 2026-02-08 13:13:43.306075

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite


# revision identifiers, used by Alembic.
revision: str = 'e69b6de02222'
down_revision: Union[str, Sequence[str], None] = '956cd4f9c8eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 创建 tweets 表（不包含 deduplication_group_id 外键，稍后添加）
    op.create_table(
        'tweets',
        sa.Column('tweet_id', sa.String(length=255), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('author_username', sa.String(length=255), nullable=False),
        sa.Column('author_display_name', sa.String(length=255), nullable=True),
        sa.Column('referenced_tweet_id', sa.String(length=255), nullable=True),
        sa.Column('reference_type', sa.String(length=20), nullable=True),
        sa.Column('media', sa.JSON(), nullable=True),
        sa.Column('deduplication_group_id', sa.String(length=255), nullable=True),
        sa.Column('db_created_at', sa.DateTime(), nullable=False),
        sa.Column('db_updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['referenced_tweet_id'], ['tweets.tweet_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('tweet_id')
    )

    # 创建 deduplication_groups 表（不包含 representative_tweet_id 外键，稍后添加）
    op.create_table(
        'deduplication_groups',
        sa.Column('group_id', sa.String(length=255), nullable=False),
        sa.Column('representative_tweet_id', sa.String(length=255), nullable=False),
        sa.Column('deduplication_type', sa.String(length=20), nullable=False),
        sa.Column('similarity_score', sa.Float(), nullable=True),
        sa.Column('tweet_ids', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('group_id')
    )

    # 添加 deduplication_group_id 外键约束（tweets -> deduplication_groups）
    with op.batch_alter_table('tweets') as batch_op:
        batch_op.create_foreign_key(
            'fk_tweets_deduplication_group_id',
            'deduplication_groups',
            ['deduplication_group_id'],
            ['group_id'],
            ondelete='SET NULL'
        )

    # 添加 representative_tweet_id 外键约束（deduplication_groups -> tweets）
    with op.batch_alter_table('deduplication_groups') as batch_op:
        batch_op.create_foreign_key(
            'fk_deduplication_groups_representative_tweet_id',
            'tweets',
            ['representative_tweet_id'],
            ['tweet_id'],
            ondelete='CASCADE'
        )

    # 创建 summaries 表
    op.create_table(
        'summaries',
        sa.Column('summary_id', sa.String(length=36), nullable=False),
        sa.Column('tweet_id', sa.String(length=255), nullable=False),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('translation_text', sa.Text(), nullable=True),
        sa.Column('model_provider', sa.String(length=50), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('cached', sa.Boolean(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('is_generated_summary', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tweet_id'], ['tweets.tweet_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('summary_id'),
        sa.UniqueConstraint('tweet_id')
    )

    # 创建索引以优化查询性能
    # tweets 表索引
    op.create_index('ix_tweets_author_username', 'tweets', ['author_username'], unique=False)
    op.create_index('ix_tweets_created_at', 'tweets', ['created_at'], unique=False)
    op.create_index('ix_tweets_deduplication_group_id', 'tweets', ['deduplication_group_id'], unique=False)

    # summaries 表索引
    op.create_index('ix_summaries_tweet_id', 'summaries', ['tweet_id'], unique=False)
    op.create_index('ix_summaries_content_hash', 'summaries', ['content_hash'], unique=False)
    op.create_index('ix_summaries_cached', 'summaries', ['cached'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""

    # 删除索引
    op.drop_index('ix_summaries_cached', table_name='summaries')
    op.drop_index('ix_summaries_content_hash', table_name='summaries')
    op.drop_index('ix_summaries_tweet_id', table_name='summaries')

    op.drop_index('ix_tweets_deduplication_group_id', table_name='tweets')
    op.drop_index('ix_tweets_created_at', table_name='tweets')
    op.drop_index('ix_tweets_author_username', table_name='tweets')

    # 删除外键约束
    with op.batch_alter_table('tweets') as batch_op:
        batch_op.drop_constraint('fk_tweets_deduplication_group_id', type_='foreignkey')

    with op.batch_alter_table('deduplication_groups') as batch_op:
        batch_op.drop_constraint('fk_deduplication_groups_representative_tweet_id', type_='foreignkey')

    # 删除表（注意顺序：先删除有外键的表）
    op.drop_table('summaries')
    op.drop_table('deduplication_groups')
    op.drop_table('tweets')
