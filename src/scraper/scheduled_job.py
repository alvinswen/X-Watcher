"""定时抓取任务模块。

将定时任务逻辑从 main.py 中解耦，避免循环导入。
供 main.py（lifespan）和 schedule_service.py 共同使用。
"""

import logging
from datetime import datetime

from src.config import get_settings
from src.scraper.scraping_service import ScrapingService
from src.scraper.task_registry import TaskRegistry, TaskStatus

logger = logging.getLogger(__name__)

# 上次定时抓取完成时间（模块级变量，用于日志追踪）
_last_scrape_time: datetime | None = None


def get_active_follows_from_db() -> list[str]:
    """从数据库获取活跃关注账号列表。

    优先从 ScraperFollow 表读取活跃账号，用于定时抓取。
    如果查询失败，返回空列表（由调用方降级到环境变量）。

    Returns:
        list[str]: 活跃关注账号的用户名列表
    """
    try:
        import asyncio

        from src.database.async_session import get_async_session_maker
        from src.preference.infrastructure.scraper_config_repository import (
            ScraperConfigRepository,
        )

        async def _fetch():
            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = ScraperConfigRepository(session)
                follows = await repo.get_all_follows(include_inactive=False)
                return [f.username for f in follows]

        return asyncio.run(_fetch())
    except Exception as e:
        logger.warning(f"从数据库获取关注列表失败，将使用环境变量: {e}")
        return []


def scheduled_scrape_job():
    """定时抓取任务。

    由 APScheduler 定期调用，执行推文抓取。
    优先从数据库 ScraperFollow 表读取关注列表，
    如果数据库中没有数据，降级到环境变量 SCRAPER_USERNAMES。
    """
    global _last_scrape_time

    settings = get_settings()

    # 检查是否启用抓取
    if not settings.scraper_enabled:
        logger.debug("抓取器已禁用，跳过定时任务")
        return

    # 1. 优先从数据库获取活跃关注列表
    usernames = get_active_follows_from_db()

    # 2. 降级：如果数据库无数据，使用环境变量
    if not usernames:
        usernames = [
            u.strip()
            for u in settings.scraper_usernames.split(",")
            if u.strip()
        ]
        if usernames:
            logger.info(f"数据库无关注列表，使用环境变量配置: {usernames}")

    if not usernames:
        logger.warning("未配置关注用户列表（数据库和环境变量均为空），跳过定时任务")
        return

    # 打印距上次抓取的时间间隔
    if _last_scrape_time:
        elapsed = datetime.now() - _last_scrape_time
        logger.info(f"定时抓取任务开始，距上次抓取: {elapsed}，用户: {usernames}")
    else:
        logger.info(f"定时抓取任务开始（首次执行），用户: {usernames}")

    # 检查是否有相同的任务正在运行
    registry = TaskRegistry.get_instance()
    for task in registry.get_all_tasks():
        if task["status"] == TaskStatus.RUNNING:
            logger.info(f"已有任务正在运行: {task['task_id']}，跳过本次执行")
            return

    # 创建并执行抓取任务
    try:
        import asyncio

        service = ScrapingService()
        task_id = asyncio.run(
            service.scrape_users(
                usernames=usernames,
                limit=settings.scraper_limit,
            )
        )
        _last_scrape_time = datetime.now()
        logger.info(
            f"定时抓取任务完成: {task_id}，"
            f"下次执行: {settings.scraper_interval} 秒后"
        )
    except Exception as e:
        logger.exception(f"定时抓取任务失败: {e}")
