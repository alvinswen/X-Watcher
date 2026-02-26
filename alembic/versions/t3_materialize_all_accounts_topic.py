"""materialize all-accounts topic

将"全部账号"从特殊的 topic_id=NULL 逻辑改为 topics 表中的真实记录。
1. 插入"全部账号"主题
2. 将所有活跃 scraper_follows 关联到该主题
3. 将 topic_summary_tasks 中 topic_id IS NULL 的行迁移到新主题
4. 恢复 topic_id 为 NOT NULL，ondelete 改回 CASCADE

Revision ID: t3_materialize_all_accounts
Revises: t2_nullable_topic_id
Create Date: 2026-02-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t3_materialize_all_accounts"
down_revision: Union[str, None] = "t2_nullable_topic_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# SQLite 匿名 FK naming convention，用于 batch 模式识别约束
naming_convention = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}

TOPIC_NAME = "全部账号"
TOPIC_DESC = "包含系统中所有活跃抓取账号的默认主题"


def upgrade() -> None:
    """创建"全部账号"主题并迁移数据，恢复 NOT NULL 约束。"""
    conn = op.get_bind()

    # 1. 检查是否已存在同名主题（幂等性）
    existing = conn.execute(
        sa.text("SELECT id FROM topics WHERE name = :name"),
        {"name": TOPIC_NAME},
    ).fetchone()

    if existing:
        topic_id = existing[0]
    else:
        # 插入"全部账号"主题（CURRENT_TIMESTAMP 是 SQL 标准，SQLite/PostgreSQL 通用）
        conn.execute(
            sa.text(
                "INSERT INTO topics (name, description, created_at, updated_at) "
                "VALUES (:name, :desc, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"name": TOPIC_NAME, "desc": TOPIC_DESC},
        )
        row = conn.execute(
            sa.text("SELECT id FROM topics WHERE name = :name"),
            {"name": TOPIC_NAME},
        ).fetchone()
        assert row is not None, f"Failed to insert topic '{TOPIC_NAME}'"
        topic_id = row[0]

    # 2. 将所有活跃 scraper_follows 关联到该主题（跳过已关联的）
    dialect_name = conn.dialect.name
    if dialect_name == "sqlite":
        insert_sql = (
            "INSERT OR IGNORE INTO topic_accounts (topic_id, username, added_at) "
            "SELECT :topic_id, username, CURRENT_TIMESTAMP "
            "FROM scraper_follows WHERE is_active = 1"
        )
    else:
        insert_sql = (
            "INSERT INTO topic_accounts (topic_id, username, added_at) "
            "SELECT :topic_id, username, CURRENT_TIMESTAMP "
            "FROM scraper_follows WHERE is_active = 1 "
            "ON CONFLICT DO NOTHING"
        )
    conn.execute(sa.text(insert_sql), {"topic_id": topic_id})

    # 3. 将 topic_id IS NULL 的摘要任务迁移到新主题
    conn.execute(
        sa.text(
            "UPDATE topic_summary_tasks SET topic_id = :topic_id WHERE topic_id IS NULL"
        ),
        {"topic_id": topic_id},
    )

    # 4. 恢复 NOT NULL 约束，ondelete 改回 CASCADE
    with op.batch_alter_table(
        "topic_summary_tasks", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_topic_summary_tasks_topic_id_topics", type_="foreignkey"
        )
        batch_op.alter_column("topic_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_topic_summary_tasks_topic_id_topics",
            "topics",
            ["topic_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """恢复 nullable + SET NULL，删除"全部账号"主题（级联删除关联数据）。"""
    conn = op.get_bind()

    # 1. 恢复 nullable + SET NULL
    with op.batch_alter_table(
        "topic_summary_tasks", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_topic_summary_tasks_topic_id_topics", type_="foreignkey"
        )
        batch_op.alter_column("topic_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            "fk_topic_summary_tasks_topic_id_topics",
            "topics",
            ["topic_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 2. 将"全部账号"主题的摘要任务 topic_id 设回 NULL
    existing = conn.execute(
        sa.text("SELECT id FROM topics WHERE name = :name"),
        {"name": TOPIC_NAME},
    ).fetchone()

    if existing:
        topic_id = existing[0]
        conn.execute(
            sa.text(
                "UPDATE topic_summary_tasks SET topic_id = NULL WHERE topic_id = :topic_id"
            ),
            {"topic_id": topic_id},
        )
        # 删除"全部账号"主题（CASCADE 会删除 topic_accounts 中的关联）
        conn.execute(
            sa.text("DELETE FROM topics WHERE id = :topic_id"),
            {"topic_id": topic_id},
        )
