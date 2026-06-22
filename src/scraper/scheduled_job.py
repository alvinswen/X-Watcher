"""定时抓取任务模块。

将定时任务逻辑从 main.py 中解耦，避免循环导入。
供 main.py（lifespan）和 schedule_service.py 共同使用。
"""

import asyncio
import logging
from datetime import datetime

from src.config import get_settings
from src.scraper.scraping_service import ScrapingService
from src.scraper.task_registry import TaskRegistry, TaskStatus

logger = logging.getLogger(__name__)

# 上次定时抓取完成时间（模块级变量，用于日志追踪）
_last_scrape_time: datetime | None = None


def _run_async(coro):
    """在后台线程中安全运行 async coroutine。

    APScheduler 的 BackgroundScheduler 在独立后台线程中运行 job，
    通常没有 running event loop，可以直接 asyncio.run()。
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
    follows_data = get_active_follows_from_db()
    usernames = [f["username"] for f in follows_data]
    manual_limits = {
        f["username"]: f["manual_limit"]
        for f in follows_data
        if f["manual_limit"]
    }

    # 2. 降级：如果数据库无数据，使用环境变量
    if not usernames:
        usernames = [
            u.strip()
            for u in settings.scraper_usernames.split(",")
            if u.strip()
        ]
        manual_limits = {}
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

    if manual_limits:
        logger.info(f"手动 limit 配置: {manual_limits}")

    # 检查是否有相同的任务正在运行
    registry = TaskRegistry.get_instance()
    for task in registry.get_all_tasks():
        if task["status"] == TaskStatus.RUNNING:
            logger.info(f"已有任务正在运行: {task['task_id']}，跳过本次执行")
            return

    # 0. 执行待回溯用户的全量抓取（常规抓取之前）
    backfill_usernames = get_pending_backfill_users_from_db()
    if backfill_usernames:
        logger.info(f"发现 {len(backfill_usernames)} 个待回溯用户: {backfill_usernames}")
        backfill_service = ScrapingService()
        try:
            for bf_username in backfill_usernames:
                try:
                    bf_result = _run_async(
                        backfill_service.backfill_user(bf_username)
                    )
                    logger.info(
                        f"回溯完成: {bf_username}, "
                        f"pages={bf_result['pages']}, new={bf_result['new']}"
                    )
                except Exception as e:
                    logger.exception(f"回溯用户 {bf_username} 失败: {e}")
        finally:
            _run_async(backfill_service.close())

    # 创建并执行抓取任务
    service = ScrapingService()
    try:
        task_id = _run_async(
            service.scrape_users(
                usernames=usernames,
                limit=settings.scraper_limit,
                manual_limits=manual_limits or None,
            )
        )
        _last_scrape_time = datetime.now()
        logger.info(
            f"定时抓取任务完成: {task_id}，"
            f"下次执行: {settings.scraper_interval} 秒后"
        )
    except Exception as e:
        logger.exception(f"定时抓取任务失败: {e}")
    finally:
        _run_async(service.close())
