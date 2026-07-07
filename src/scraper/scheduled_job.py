"""抓取账号查询桥。

保留给手动抓取和回溯任务复用的关注账号查询函数。
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
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


async def get_active_follows_async() -> list[dict[str, Any]]:
    """异步获取活跃关注(含 manual_limit),供 async 上下文(running loop)直接 await。"""
    try:
        from src.data_layer.provider import get_follows_repo

        follows = await get_follows_repo().get_active_follows()
        return [{"username": f.username, "manual_limit": f.manual_limit} for f in follows]
    except Exception as e:
        logger.warning(f"从数据库获取关注列表失败，将使用环境变量: {e}")
        return []


async def get_pending_backfill_users_async() -> list[str]:
    """异步获取待回溯用户名(is_active 且 backfill_status=pending),供 async 上下文 await。"""
    try:
        from src.data_layer.provider import get_follows_repo

        follows = await get_follows_repo().get_pending_backfill_users()
        return [f.username for f in follows]
    except Exception as e:
        logger.warning(f"获取待回溯用户列表失败: {e}")
        return []


def get_active_follows_from_db() -> list[dict[str, Any]]:
    """同步桥:供后台调度线程(无 running loop)调用。

    经 _run_async(asyncio.run)桥接文件层。
    """
    try:
        return _run_async(get_active_follows_async())
    except Exception as e:
        logger.warning(f"从数据库获取关注列表失败，将使用环境变量: {e}")
        return []


def get_pending_backfill_users_from_db() -> list[str]:
    """同步桥:供后台调度线程(无 running loop)调用。"""
    try:
        return _run_async(get_pending_backfill_users_async())
    except Exception as e:
        logger.warning(f"获取待回溯用户列表失败: {e}")
        return []
