"""Drop preference tables and priority column

移除已裁剪的用户偏好功能相关表和字段：
- 删除 filter_rules 表
- 删除 preferences 表（如存在）
- 从 twitter_follows 移除 priority 列、updated_at 列及相关约束/索引

Revision ID: f1a2b3c4d5e6
Revises: d5e6f7g8h9i0
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7g8h9i0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """移除偏好相关表和字段。"""
    # 删除 filter_rules 表
    op.drop_index('idx_filter_rules_user_id', table_name='filter_rules')
    op.drop_index('idx_filter_rules_type', table_name='filter_rules')
    op.drop_table('filter_rules')

    # 从 twitter_follows 移除 priority 和 updated_at 列
    with op.batch_alter_table('twitter_follows') as batch_op:
        batch_op.drop_index('idx_twitter_follows_priority')
        batch_op.drop_constraint('ck_twitter_follows_priority_range', type_='check')
        batch_op.drop_column('priority')
        batch_op.drop_column('updated_at')


def downgrade() -> None:
    """恢复偏好相关表和字段。"""
    # 恢复 twitter_follows 的 priority 和 updated_at 列
    with op.batch_alter_table('twitter_follows') as batch_op:
        batch_op.add_column(
            sa.Column('priority', sa.Integer(), nullable=False, server_default='5')
        )
        batch_op.add_column(
            sa.Column('updated_at', sa.DateTime(), nullable=False,
                       server_default=sa.text('CURRENT_TIMESTAMP'))
        )
        batch_op.create_check_constraint(
            'ck_twitter_follows_priority_range',
            'priority BETWEEN 1 AND 10'
        )
        batch_op.create_index('idx_twitter_follows_priority', ['priority'])

    # 恢复 filter_rules 表
    op.create_table(
        'filter_rules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('filter_type', sa.String(length=20), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "filter_type IN ('keyword', 'hashtag', 'content_type')",
            name='ck_filter_rules_type'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_filter_rules_type', 'filter_rules', ['filter_type'])
    op.create_index('idx_filter_rules_user_id', 'filter_rules', ['user_id'])
