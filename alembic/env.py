from logging.config import fileConfig
import sys
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 导入项目配置和模型
from src.config import get_settings
from src.database.models import Base

# 导入所有 ORM 模型以确保它们被注册到 Base.metadata
# 必须导入所有继承自 Base 的模型类
import src.scraper.infrastructure.models  # noqa: F401 导入 TweetOrm, DeduplicationGroupOrm
import src.scraper.infrastructure.fetch_stats_models  # noqa: F401 导入 FetchStatsOrm
import src.summarization.infrastructure.models  # noqa: F401 导入 SummaryOrm

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# 从项目配置获取数据库 URL
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 添加模型的 MetaData 对象，用于 'autogenerate' 支持
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # 从项目配置创建异步引擎的同步版本用于迁移
    from sqlalchemy import create_engine

    # 获取同步版本的数据库 URL
    sync_url = settings.database_url.replace(
        "sqlite+aiosqlite:///", "sqlite:///"
    ).replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    connectable = create_engine(
        sync_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,  # SQLite 需要 batch 模式来修改表结构
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
