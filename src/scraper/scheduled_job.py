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


async def resolve_manual_limits(usernames: list[str]) -> dict[str, int]:
    """解析给定用户名中已配置手动抓取上限(manual_limit)的账号映射。

    REST(``_run_scraping_task_async``)与 MCP(``trigger_scrape``)两条抓取触发
    路径共享本函数，取代此前"REST 自行读取、MCP 完全不读"的分叉实现(CHG-031)。

    fail-soft：底层 get_active_follows_async 查询失败时已记录警告日志并返回
    空列表，本函数据此返回空字典，调用方应视为"该批账号均无手动限额"，退化用
    默认 limit 继续抓取，不中断整体任务。

    Args:
        usernames: 本次抓取目标账号列表，仅返回其中配置了 manual_limit 的子集

    Returns:
        {username: manual_limit}，只含 usernames 范围内且确实配置了正数
        manual_limit 的账号
    """
    follows_data = await get_active_follows_async()
    manual_limits = {
        f["username"]: f["manual_limit"]
        for f in follows_data
        if f["manual_limit"] and f["username"] in usernames
    }
    if manual_limits:
        logger.info(f"抓取任务使用 manual_limits: {manual_limits}")
    return manual_limits
