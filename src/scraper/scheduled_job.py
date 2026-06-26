"""抓取账号查询桥。

保留给手动抓取和回溯任务复用的关注账号查询函数。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在后台线程中安全运行 async coroutine。

    后台线程通常没有 running event loop，可以直接 asyncio.run()。
    但为安全起见，提供 fallback：若线程已有 event loop 则创建新的。
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _active_follows_sync_query() -> list[dict]:
    """sqlalchemy 模式:同步 SyncSession 直查(原实现,零行为变化 + 兼容 sync 测试隔离)。"""
    from sqlalchemy import select
    from sqlalchemy.orm import Session as SyncSession

    from src.database.models import ScraperFollow, get_engine

    engine = get_engine()
    with SyncSession(engine) as session:
        result = session.execute(
            select(ScraperFollow.username, ScraperFollow.manual_limit).where(
                ScraperFollow.is_active == True  # noqa: E712
            )
        )
        return [{"username": row[0], "manual_limit": row[1]} for row in result]


def _pending_backfill_sync_query() -> list[str]:
    """sqlalchemy 模式:同步 SyncSession 直查(原实现)。"""
    from sqlalchemy import select
    from sqlalchemy.orm import Session as SyncSession

    from src.database.models import ScraperFollow, get_engine

    engine = get_engine()
    with SyncSession(engine) as session:
        result = session.execute(
            select(ScraperFollow.username).where(
                ScraperFollow.is_active == True,  # noqa: E712
                ScraperFollow.backfill_status == "pending",
            )
        )
        return [row[0] for row in result]


async def get_active_follows_async() -> list[dict]:
    """异步获取活跃关注(含 manual_limit),供 async 上下文(running loop)直接 await。

    file 模式走文件层;sqlalchemy 模式复用同步直查(保持原行为 + 兼容 sync 测试隔离)。
    """
    try:
        from src.data_layer.provider import _data_layer, get_follows_repo

        if _data_layer() == "file":
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                follows = await get_follows_repo(session).get_active_follows()
            return [{"username": f.username, "manual_limit": f.manual_limit} for f in follows]
        return _active_follows_sync_query()
    except Exception as e:
        logger.warning(f"从数据库获取关注列表失败，将使用环境变量: {e}")
        return []


async def get_pending_backfill_users_async() -> list[str]:
    """异步获取待回溯用户名(is_active 且 backfill_status=pending),供 async 上下文 await。"""
    try:
        from src.data_layer.provider import _data_layer, get_follows_repo

        if _data_layer() == "file":
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                follows = await get_follows_repo(session).get_pending_backfill_users()
            return [f.username for f in follows]
        return _pending_backfill_sync_query()
    except Exception as e:
        logger.warning(f"获取待回溯用户列表失败: {e}")
        return []


def get_active_follows_from_db() -> list[dict]:
    """同步桥:供后台调度线程(无 running loop)调用。

    file 模式经 _run_async(asyncio.run)桥接文件层;sqlalchemy 模式走原同步直查。
    """
    try:
        from src.data_layer.provider import _data_layer

        if _data_layer() == "file":
            return _run_async(get_active_follows_async())
        return _active_follows_sync_query()
    except Exception as e:
        logger.warning(f"从数据库获取关注列表失败，将使用环境变量: {e}")
        return []


def get_pending_backfill_users_from_db() -> list[str]:
    """同步桥:供后台调度线程(无 running loop)调用。"""
    try:
        from src.data_layer.provider import _data_layer

        if _data_layer() == "file":
            return _run_async(get_pending_backfill_users_async())
        return _pending_backfill_sync_query()
    except Exception as e:
        logger.warning(f"获取待回溯用户列表失败: {e}")
        return []
