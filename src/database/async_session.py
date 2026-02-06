"""异步数据库会话管理。

提供异步 SQLAlchemy 引擎和会话工厂。
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# 延迟初始化
_async_engine = None
_async_session_maker = None


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
