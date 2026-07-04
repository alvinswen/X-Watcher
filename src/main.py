"""FastAPI 应用入口。"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings, validate_jwt_secret_strength
from src.database.models import Base
from src.database.models import get_engine as engine
from src.logging_config import setup_logging

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

# 服务启动时间
_server_start_time: datetime | None = None


def get_server_start_time() -> datetime | None:
    """获取服务启动时间。供 status 路由使用。"""
    return _server_start_time


def _init_db_if_needed():
    """启动期 DB 初始化:建表。

    file 模式(pg 下线守卫):跳过 create_all,避免重建已 DROP 的 pg 表。
    """
    from src.data_layer.provider import is_file_mode

    if is_file_mode():
        logger.info("file 模式:跳过 create_all(pg 下线守卫)")
        return

    Base.metadata.create_all(engine())


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 - app 参数是 FastAPI 要求的
    """应用生命周期管理。

    启动时创建数据库表并执行启动安全检查。
    """
    settings = get_settings()

    # 确保所有 ORM 模型在 create_all 前已注册到 Base.metadata
    # （分散在各子模块的模型需显式导入，否则 create_all 不会建表）
    from src.scraper.infrastructure.article_models import ArticleOrm  # noqa: F401

    # 启动时创建数据库表 + 内联迁移（file 模式跳过，pg 下线守卫）
    _init_db_if_needed()

    # 安全检查：JWT 弱密钥直接拒绝启动
    validate_jwt_secret_strength(settings)

    # 恢复僵尸任务（内存 + 数据库残留的 RUNNING 记录）
    from src.scraper.task_registry import TaskRegistry

    registry = TaskRegistry.get_instance()
    recovered = registry.recover_stale_tasks(
        max_running_seconds=settings.task_max_running_seconds,
    )
    if recovered > 0:
        logger.warning(f"启动时恢复了 {recovered} 个僵尸任务")

    # 记录服务启动时间
    global _server_start_time
    _server_start_time = datetime.now(timezone.utc)

    yield


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
    allow_credentials=False,  # ACAO=* 与 ACAC=true 是非法组合，会让浏览器拒绝 cross-origin module 响应（动态懒加载的路由切换会失败）。本服务用 X-API-Key header 认证，不依赖 cookie credentials。
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

    检查数据库连接，返回组件健康信息。
    始终返回 HTTP 200 以兼容 Docker HEALTHCHECK。
    """
    from sqlalchemy import text

    from src.data_layer.provider import is_file_mode
    from src.database.async_session import get_async_session_maker

    components = {}

    # 1. 数据库连接检查
    if is_file_mode():
        # file 模式(pg 下线守卫):不连 pg,改探数据目录存在性
        from src.data_layer.provider import data_root

        root = data_root()
        if root.exists():
            components["database"] = {
                "status": "healthy",
                "mode": "file",
                "data_root": str(root),
            }
        else:
            components["database"] = {
                "status": "unhealthy",
                "error": f"data_root 不存在: {root}",
            }
    else:
        try:
            session_maker = get_async_session_maker()
            async with session_maker() as session:
                await session.execute(text("SELECT 1"))
            components["database"] = {"status": "healthy"}
        except Exception as e:
            components["database"] = {"status": "unhealthy", "error": str(e)}

    # 2. 整体状态判定
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

# 注册 Subject 议题 API 路由
from src.subjects.api.routes import router as subjects_router

app.include_router(subjects_router)

# 注册用户管理 API 路由
from src.user.api import admin_user_router, auth_router, user_router

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(admin_user_router)

# 注册 Prometheus 监控路由
from src.monitoring import routes as monitoring_routes

app.include_router(monitoring_routes.router)

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

# 注册数据同步 API 路由
from src.api.routes.sync_routes import router as sync_router

app.include_router(sync_router)

# 配置前端静态资源服务（如果存在）
import os

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
            if (
                path.startswith("/api")
                or path.startswith("/docs")
                or path.startswith("/redoc")
                or path.startswith("/openapi")
                or path.startswith("/metrics")
                or path == "/health"
                or path.startswith("/assets")
            ):
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
