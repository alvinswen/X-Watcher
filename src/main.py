"""FastAPI 应用入口。"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.database.models import Base
from src.database.models import get_engine as engine
from src.scraper import ScrapingService, TaskRegistry, TaskStatus

logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler: BackgroundScheduler | None = None

# 上次定时抓取完成时间（模块级变量，用于日志追踪）
_last_scrape_time: datetime | None = None


def _get_active_follows_from_db() -> list[str]:
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


def _scheduled_scrape_job():
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
    usernames = _get_active_follows_from_db()

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


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 - app 参数是 FastAPI 要求的
    """应用生命周期管理。

    启动时创建数据库表并初始化调度器。
    关闭时停止调度器。
    """
    global _scheduler

    settings = get_settings()

    # 启动时创建数据库表
    Base.metadata.create_all(engine())

    # 初始化调度器
    if settings.scraper_enabled:
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

        # 添加定时任务（启动时立即执行首次抓取）
        _scheduler.add_job(
            _scheduled_scrape_job,
            "interval",
            seconds=settings.scraper_interval,
            id="scraper_job",
            name="定时抓取推文",
            max_instances=1,  # 防止任务重复执行
            replace_existing=True,
            next_run_time=datetime.now(),  # 启动后立即执行第一次
        )

        _scheduler.start()
        logger.info(
            f"调度器已启动，间隔: {settings.scraper_interval} 秒"
        )

    yield

    # 关闭时的清理工作
    if _scheduler:
        _scheduler.shutdown(wait=True)
        logger.info("调度器已停止")


# 创建 FastAPI 应用
app = FastAPI(
    title="X-watcher",
    description="面向 Agent 的 X 平台智能信息监控服务",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配置 Prometheus 监控中间件（在 CORS 之后）
from src.monitoring.middleware import PrometheusMiddleware

settings = get_settings()
if settings.prometheus_enabled:
    app.add_middleware(PrometheusMiddleware)


@app.get("/health")
async def health_check():
    """健康检查端点。"""
    return {"status": "healthy"}


# 导入并注册 API 路由
from src.api.routes import admin
from src.api.routes.tweets import router as tweets_router
from src.deduplication.api import routes as deduplication_routes
from src.summarization.api import routes as summarization_routes

app.include_router(admin.router)
app.include_router(tweets_router)
app.include_router(deduplication_routes.router)
app.include_router(summarization_routes.router)

# 注册偏好管理 API 路由
from src.preference.api.routes import scraper_config_router, scraper_public_router, preference_router

app.include_router(scraper_config_router)
app.include_router(scraper_public_router)
app.include_router(preference_router)

# 注册 Feed API 路由
from src.feed.api.routes import router as feed_router

app.include_router(feed_router)

# 注册用户管理 API 路由
from src.user.api import auth_router, user_router, admin_user_router

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(admin_user_router)

# 注册 Prometheus 监控路由
from src.monitoring import routes as monitoring_routes

app.include_router(monitoring_routes.router)

# 配置前端静态资源服务（如果存在）
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

web_dir = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.exists(web_dir):
    # 挂载静态资源目录
    assets_dir = os.path.join(web_dir, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    # 创建 SPA 中间件
    class SPAMiddleware(BaseHTTPMiddleware):
        """SPA 前端中间件 - 为非 API 路径返回 index.html"""

        async def dispatch(self, request: Request, call_next):
            """处理请求"""
            path = request.url.path

            # 跳过 API 路径和系统路径
            if (path.startswith("/api") or
                path.startswith("/docs") or
                path.startswith("/redoc") or
                path.startswith("/openapi") or
                path.startswith("/metrics") or
                path == "/health" or
                path.startswith("/assets")):
                return await call_next(request)

            # 对于其他路径，返回 index.html（如果存在）
            index_path = os.path.join(web_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)

            # 如果 index.html 不存在，正常处理
            return await call_next(request)

    # 添加 SPA 中间件（必须在所有路由注册之后）
    app.add_middleware(SPAMiddleware)

    logger.info(f"前端 SPA 中间件已启用: {web_dir}")


def main():
    """主函数 - 用于开发服务器启动。"""
    import uvicorn

    from src.config import get_settings

    settings = get_settings()

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
