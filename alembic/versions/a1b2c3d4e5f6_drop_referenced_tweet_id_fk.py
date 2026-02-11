"""drop_referenced_tweet_id_fk

移除 tweets.referenced_tweet_id 的自引用外键约束。

该外键要求被引用推文必须存在于 DB 中，但实际抓取场景下被引用推文大概率不在数据库中，
导致 referenced_tweet_id 被应用层置为 NULL，丢失了抓取到的原始数据。
移除 FK 后 referenced_tweet_id 成为普通字符串列，可完整保存外部推文 ID。

Revision ID: a1b2c3d4e5f6
Revises: e69b6de02222
Create Date: 2026-02-09 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e69b6de02222'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# SQLite 的匿名 FK 需要通过 naming_convention 来让 batch 模式识别
naming_convention = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    """移除 referenced_tweet_id 的外键约束。"""
    # SQLite 不支持 ALTER TABLE DROP CONSTRAINT，必须使用 batch 模式
    # batch_alter_table 会重建整张表来实现约束变更
    # naming_convention 让 batch 模式能通过反射找到匿名 FK
    with op.batch_alter_table(
        "tweets", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_tweets_referenced_tweet_id_tweets",
            type_="foreignkey",
        )


def downgrade() -> None:
    """恢复 referenced_tweet_id 的外键约束。"""
    with op.batch_alter_table(
        "tweets", naming_convention=naming_convention
    ) as batch_op:
        batch_op.create_foreign_key(
            "fk_tweets_referenced_tweet_id_tweets",
            "tweets",
            ["referenced_tweet_id"],
            ["tweet_id"],
            ondelete="SET NULL",
        )
