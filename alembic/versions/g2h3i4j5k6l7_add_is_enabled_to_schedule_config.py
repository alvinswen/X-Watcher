"""add is_enabled to scraper_schedule_config

修复缺失的 is_enabled 列。ORM 模型已定义该字段，但原始建表迁移
(492f70102988) 遗漏了此列，导致启用/禁用调度操作时报错。

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 is_enabled 列到 scraper_schedule_config 表。"""
    op.add_column('scraper_schedule_config',
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='1'))


def downgrade() -> None:
    """移除 is_enabled 列。"""
    op.drop_column('scraper_schedule_config', 'is_enabled')
