"""admin 后台任务取活跃关注助手。

供手动抓取/回溯任务(async 上下文)读取活跃关注账号与 manual_limit。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_active_follows_async() -> list[dict[str, Any]]:
    """异步获取活跃关注(含 manual_limit),供 async 上下文(running loop)直接 await。"""
    try:
        from src.data_layer.provider import get_follows_repo

        follows = await get_follows_repo().get_active_follows()
        return [{"username": f.username, "manual_limit": f.manual_limit} for f in follows]
    except Exception as e:
        logger.warning(f"获取关注列表失败，返回空列表: {e}")
        return []
