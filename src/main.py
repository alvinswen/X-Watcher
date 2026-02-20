"""FastAPI 应用入口。"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.database.models import Base
from src.database.models import get_engine as engine
from src.logging_config import setup_logging
from src.scheduler_accessor import register_scheduler, unregister_scheduler
from src.scraper.scheduled_job import scheduled_scrape_job

# 配置应用层日志：结构化格式 + 文件轮转 + trace_id 支持
_settings = get_settings()
setup_logging(
    level=_settings.log_level,
    log_format=_settings.log_format,
    log_file=_settings.log_file or None,
    log_file_max_bytes=_settings.log_file_max_bytes,
    log_file_backup_count=_settings.log_file_backup_count,
)

logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler: BackgroundScheduler | None = None

# 服务启动时间
_server_start_time: datetime | None = None


def get_server_start_time() -> datetime | None:
    """获取服务启动时间。供 status 路由使用。"""
    return _server_start_time


async def _get_schedule_config_from_db() -> tuple[int | None, datetime | None, bool]:
    """从数据库获取调度配置。

    在 lifespan async context 中直接 await 调用，避免 asyncio.run() 冲突。

    Returns:
        tuple: (interval_seconds, next_run_time, is_enabled)
               无配置时返回 (None, None, False)
    """
    try:
        from src.database.async_session import get_async_session_maker
        from src.preference.infrastructure.schedule_repository import (
            ScraperScheduleRepository,
        )

        session_maker = get_async_session_maker()
        async with session_maker() as session:
            repo = ScraperScheduleRepository(session)
            config = await repo.get_schedule_config()
            if config:
                return (config.interval_seconds, config.next_run_time, config.is_enabled)
            return (None, None, False)
    except Exception as e:
        logger.warning(f"从数据库获取调度配置失败: {e}")
        return (None, None, False)


def _migrate_schedule_config_table():
    """为 scraper_schedule_config 表添加 is_enabled 列（如果不存在）。"""
    try:
        from sqlalchemy import text
        eng = engine()
        with eng.connect() as conn:
            conn.execute(
                text("ALTER TABLE scraper_schedule_config ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT 1")
            )
            conn.commit()
            logger.info("数据库迁移：已添加 scraper_schedule_config.is_enabled 列")
    except Exception:
        # 列已存在或表不存在时忽略
        pass


def _migrate_scheduler_execution_log_table():
    """创建 scheduler_execution_log 表（如果不存在）。"""
    try:
        from sqlalchemy import text

        eng = engine()
        with eng.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS scheduler_execution_log ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "job_id VARCHAR(100) NOT NULL,"
                    "event_type VARCHAR(20) NOT NULL,"
                    "executed_at DATETIME NOT NULL,"
                    "duration_seconds FLOAT,"
                    "error_type VARCHAR(200),"
                    "error_message TEXT,"
                    "next_run_time DATETIME,"
                    "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scheduler_log_job_id "
                    "ON scheduler_execution_log(job_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scheduler_log_event_type "
                    "ON scheduler_execution_log(event_type)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scheduler_log_executed_at "
                    "ON scheduler_execution_log(executed_at)"
                )
            )
            conn.commit()
    except Exception:
        pass


async def _cleanup_old_scheduler_logs():
    """清理过期的调度器执行日志。"""
    try:
        from src.database.async_session import get_async_session_maker
        from src.scraper.infrastructure.scheduler_log_repository import (
            SchedulerExecutionLogRepository,
        )

        settings = get_settings()
        session_maker = get_async_session_maker()
        async with session_maker() as session:
            repo = SchedulerExecutionLogRepository(session)
            deleted = await repo.cleanup_old_logs(
                retention_days=settings.scheduler_log_retention_days
            )
            if deleted > 0:
                logger.info(f"清理了 {deleted} 条过期调度器执行日志")
    except Exception as e:
        logger.warning(f"清理调度器执行日志失败: {e}")


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

    # 迁移：确保 is_enabled 列存在
    _migrate_schedule_config_table()
    # 迁移：确保 scheduler_execution_log 表存在
    _migrate_scheduler_execution_log_table()

    # 初始化调度器
    if settings.scraper_enabled:
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        _scheduler.start()
        register_scheduler(_scheduler)

        # 注册事件监听器
        from apscheduler.events import (
            EVENT_JOB_ERROR,
            EVENT_JOB_EXECUTED,
            EVENT_JOB_MISSED,
        )

        from src.scraper.scheduler_listener import scheduler_event_listener

        _scheduler.add_listener(
            scheduler_event_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
        )
        logger.info("调度器事件监听器已注册")

        # 从 DB 加载调度配置，仅在有已启用配置时恢复 job
        db_interval, db_next_run, db_is_enabled = await _get_schedule_config_from_db()

        if db_is_enabled and db_interval is not None:
            next_run = db_next_run if db_next_run is not None else datetime.now(timezone.utc)
            _scheduler.add_job(
                scheduled_scrape_job,
                "interval",
                seconds=db_interval,
                id="scraper_job",
                name="定时抓取推文",
                max_instances=1,
                replace_existing=True,
                next_run_time=next_run,
            )
            logger.info(
                f"调度器已启动，从 DB 恢复调度任务: "
                f"interval={db_interval}s, next_run={next_run}, "
                f"is_enabled={db_is_enabled}"
            )
        else:
            logger.info(
                f"调度器已启动（空闲模式，无调度任务）: "
                f"db_interval={db_interval}, db_is_enabled={db_is_enabled}"
            )

    # 清理过期的调度器执行日志
    await _cleanup_old_scheduler_logs()

    # 启动摘要任务队列
    from src.summarization.services.summarization_queue import SummarizationQueue

    _summarization_queue = SummarizationQueue.get_instance()
    await _summarization_queue.start()

    # 记录服务启动时间
    global _server_start_time
    _server_start_time = datetime.now(timezone.utc)

    yield

    # 关闭时的清理工作（先停队列，再停调度器）
    await _summarization_queue.stop()

    if _scheduler:
        unregister_scheduler()
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
    """健康检查端点。

    检查数据库连接和调度器状态，返回各组件健康信息。
    始终返回 HTTP 200 以兼容 Docker HEALTHCHECK。
    """
    from sqlalchemy import text

    from src.database.async_session import get_async_session_maker
    from src.scheduler_accessor import get_scheduler

    components = {}

    # 1. 数据库连接检查
    try:
        session_maker = get_async_session_maker()
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
        components["database"] = {"status": "healthy"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "error": str(e)}

    # 2. 调度器状态检查
    scheduler = get_scheduler()
    if scheduler is not None:
        job = scheduler.get_job("scraper_job")
        components["scheduler"] = {
            "status": "healthy" if scheduler.running else "unhealthy",
            "running": scheduler.running,
            "jobs": len(scheduler.get_jobs()),
            "scraper_job_active": job is not None,
        }
    else:
        components["scheduler"] = {"status": "unhealthy", "error": "not initialized"}

    # 3. 整体状态判定
    overall = "healthy"
    if any(c["status"] == "unhealthy" for c in components.values()):
        overall = "degraded"

    return {"status": overall, "components": components}


# 导入并注册 API 路由
from src.api.routes import admin
from src.api.routes.tweets import router as tweets_router
from src.summarization.api import routes as summarization_routes

app.include_router(admin.router)
app.include_router(tweets_router)
app.include_router(summarization_routes.router)

# 注册偏好管理 API 路由
from src.preference.api.routes import scraper_config_router, scraper_public_router

app.include_router(scraper_config_router)
app.include_router(scraper_public_router)

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

# 注册调度器执行历史 API 路由
from src.api.routes.scheduler import router as scheduler_router

app.include_router(scheduler_router)

# 注册主题管理 API 路由
# 注意：summary_router 必须在 topic_router 之前注册，
# 因为 topic_router 的 /api/topics/{topic_id} 会拦截 /api/topics/summary-tasks
from src.topic.api.routes import router as topic_router, summary_router as topic_summary_router

app.include_router(topic_summary_router)
app.include_router(topic_router)

# 注册推文浏览 API 路由
from src.browse.api.routes import router as browse_router

app.include_router(browse_router)

# 注册搜索 API 路由
from src.search.api.routes import router as search_router

app.include_router(search_router)

# 注册系统状态 API 路由
from src.api.routes.status import router as status_router

app.include_router(status_router)

# 注册配置验证 API 路由
from src.api.routes.config_routes import router as config_router

app.include_router(config_router)

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
