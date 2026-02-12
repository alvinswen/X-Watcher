"""add scraper_schedule_config table

Revision ID: 492f70102988
Revises: c4d5e6f7g8h9
Create Date: 2026-02-12 19:04:27.702631

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '492f70102988'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('scraper_schedule_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('interval_seconds', sa.Integer(), nullable=False, server_default='43200'),
    sa.Column('next_run_time', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('scraper_schedule_config')
