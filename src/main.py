"""FastAPI 应用入口。"""

import logging
from contextlib import asynccontextmanager

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


def _scheduled_scrape_job():
    """定时抓取任务。

    由 APScheduler 定期调用，执行推文抓取。
    """
    settings = get_settings()

    # 检查是否启用抓取
    if not settings.scraper_enabled:
        logger.debug("抓取器已禁用，跳过定时任务")
        return

    # 解析用户名列表
    usernames = [
        u.strip()
        for u in settings.scraper_usernames.split(",")
        if u.strip()
    ]

    if not usernames:
        logger.warning("未配置关注用户列表，跳过定时任务")
        return

    logger.info(f"定时抓取任务开始，用户: {usernames}")

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
        logger.info(f"定时抓取任务完成: {task_id}")
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

        # 添加定时任务
        _scheduler.add_job(
            _scheduled_scrape_job,
            "interval",
            seconds=settings.scraper_interval,
            id="scraper_job",
            name="定时抓取推文",
            max_instances=1,  # 防止任务重复执行
            replace_existing=True,
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
    title="SeriousNewsAgent",
    description="智能新闻助理系统 - 面向科技公司高管的个性化新闻流",
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
from src.deduplication.api import routes as deduplication_routes
from src.summarization.api import routes as summarization_routes

app.include_router(admin.router)
app.include_router(deduplication_routes.router)
app.include_router(summarization_routes.router)

# 注册 Prometheus 监控路由
from src.monitoring import routes as monitoring_routes

app.include_router(monitoring_routes.router)


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
