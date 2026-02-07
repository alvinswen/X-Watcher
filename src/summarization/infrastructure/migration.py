"""摘要翻译模块数据库迁移脚本。

创建 summaries 表和相关索引，以及扩展 tweets 表。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upgrade(session: AsyncSession) -> None:
    """执行数据库升级。

    Args:
        session: SQLAlchemy 异步会话
    """
    # 创建 summaries 表
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS summaries (
        summary_id VARCHAR(255) PRIMARY KEY,
        tweet_id VARCHAR(255) NOT NULL,
        summary_text TEXT NOT NULL,
        translation_text TEXT,
        model_provider VARCHAR(20) NOT NULL,
        model_name VARCHAR(100) NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        completion_tokens INTEGER NOT NULL,
        total_tokens INTEGER NOT NULL,
        cost_usd REAL NOT NULL,
        cached BOOLEAN NOT NULL DEFAULT 0,
        content_hash VARCHAR(64) NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """
    await session.execute(text(create_table_sql))

    # 添加 tweets 表扩展字段（如果不存在）
    # SQLite 需要分别检查并添加列
    try:
        await session.execute(text("ALTER TABLE tweets ADD COLUMN summary_cached BOOLEAN DEFAULT 0"))
    except Exception:
        pass  # 列已存在

    try:
        await session.execute(text("ALTER TABLE tweets ADD COLUMN content_hash VARCHAR(64)"))
    except Exception:
        pass  # 列已存在

    # 创建索引
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_summaries_tweet ON summaries(tweet_id)"))
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_summaries_created ON summaries(created_at DESC)"))
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_summaries_provider ON summaries(model_provider)"))

    await session.commit()


async def downgrade(session: AsyncSession) -> None:
    """执行数据库降级。

    Args:
        session: SQLAlchemy 异步会话
    """
    # 删除索引
    await session.execute(text("DROP INDEX IF EXISTS idx_summaries_provider"))
    await session.execute(text("DROP INDEX IF EXISTS idx_summaries_created"))
    await session.execute(text("DROP INDEX IF EXISTS idx_summaries_tweet"))

    # 删除 summaries 表
    await session.execute(text("DROP TABLE IF EXISTS summaries"))

    # 注意：SQLite 不直接支持 ALTER TABLE DROP COLUMN
    # 在生产环境中需要使用重建表的方式
    # 这里为了测试目的，我们跳过删除列的步骤

    await session.commit()
