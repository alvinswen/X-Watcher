"""异步数据库会话管理。

提供异步 SQLAlchemy 引擎和会话工厂。
"""

import logging
from threading import Thread
from time import sleep

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

# 延迟初始化
_async_engine = None
_async_session_maker = None

# 数据库监控线程
_metrics_thread: Thread | None = None
_metrics_running = False


def _update_db_metrics() -> None:
    """更新数据库连接池指标。

    在后台线程中定期运行。
    """
    from src.monitoring import metrics

    global _metrics_running

    while _metrics_running:
        try:
            engine = get_async_engine()
            pool = engine.pool

            # 更新连接池指标
            metrics.db_pool_size.set(pool.size())
            metrics.db_pool_available.set(pool.checkedin())

        except Exception as e:
            logger.warning(f"更新数据库指标失败: {e}")

        # 每 5 秒更新一次
        sleep(5)


def _start_metrics_collection() -> None:
    """启动数据库指标收集线程。"""
    from src.config import get_settings

    settings = get_settings()

    if not settings.prometheus_enabled:
        return

    global _metrics_running, _metrics_thread

    if _metrics_thread is None or not _metrics_thread.is_alive():
        _metrics_running = True
        _metrics_thread = Thread(
            target=_update_db_metrics,
            daemon=True,
            name="db_metrics_collector",
        )
        _metrics_thread.start()
        logger.info("数据库连接池监控已启动")


def _stop_metrics_collection() -> None:
    """停止数据库指标收集线程。"""
    global _metrics_running

    _metrics_running = False
    logger.info("数据库连接池监控已停止")


def _get_async_database_url() -> str:
    """获取异步数据库 URL。

    将同步 URL 转换为异步 URL：
    - sqlite:///./news_agent.db -> sqlite+aiosqlite:///./news_agent.db
    - postgresql://... -> postgresql+asyncpg://...
    """
    from src.config import get_settings

    settings = get_settings()
    return settings.database_url.replace(
        "sqlite:///", "sqlite+aiosqlite:///"
    ).replace(
        "postgresql://", "postgresql+asyncpg://"
    )


def get_async_engine():
    """获取异步数据库引擎。

    Returns:
        AsyncEngine: SQLAlchemy 异步引擎
    """
    global _async_engine
    if _async_engine is None:
        from src.config import get_settings

        settings = get_settings()
        _async_engine = create_async_engine(
            _get_async_database_url(),
            echo=settings.log_level == "DEBUG",
            pool_pre_ping=True,
        )
        # 启动指标收集
        _start_metrics_collection()
    return _async_engine


def get_async_session_maker():
    """获取异步会话工厂。

    Returns:
        async_sessionmaker: 异步会话工厂
    """
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


async def get_async_session() -> AsyncSession:
    """获取异步数据库会话。

    Yields:
        AsyncSession: 异步数据库会话
    """
    async with get_async_session_maker() as session:
        yield session


# 导出（向后兼容）
async_engine = property(get_async_engine)
async_session_maker = property(get_async_session_maker)
