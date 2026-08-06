"""FastAPI 应用入口。"""

import logging
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import get_settings, validate_jwt_secret_strength
from src.logging_config import setup_logging
from src.shared.error_messages import INTERNAL_SERVER_ERROR_DETAIL

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


def _resolve_commit() -> str:
    """解析当前部署的 Git 短提交号，无法获取时返回 unknown。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
            cwd=Path(__file__).resolve().parents[1],
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


_APP_VERSION: str = _pkg_version("x-watcher")
_APP_COMMIT: str = _resolve_commit()

# 服务启动时间
_server_start_time: datetime | None = None


def get_server_start_time() -> datetime | None:
    """获取服务启动时间。供 status 路由使用。"""
    return _server_start_time


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001 - app 参数是 FastAPI 要求的
    """应用生命周期管理。

    启动时执行启动安全检查。
    """
    settings = get_settings()

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

    from src.data_layer.provider import data_root
    from src.storage.views import warm_start_by_day

    warm_start_by_day(data_root())

    # 记录服务启动时间
    global _server_start_time
    _server_start_time = datetime.now(UTC)

    yield


# 创建 FastAPI 应用
app = FastAPI(
    title="X-watcher",
    description="面向 Agent 的 X 平台智能信息监控服务",
    version=_APP_VERSION,
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """将未捕获异常归一为不泄漏内部信息的 JSON 500 响应。"""
    logger.error(
        "未捕获异常: %s %s -> 500",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": INTERNAL_SERVER_ERROR_DETAIL},
    )


# 配置 Prometheus 监控中间件（在 CORS 之后）
from src.monitoring.middleware import PrometheusMiddleware

settings = get_settings()
if settings.prometheus_enabled:
    app.add_middleware(PrometheusMiddleware)


@app.get("/health")
async def health_check():  # type: ignore[no-untyped-def]
    """健康检查端点。

    检查数据库连接，返回组件健康信息。
    始终返回 HTTP 200 以兼容 Docker HEALTHCHECK。
    """

    components = {}

    # 1. 数据目录检查
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

    # 2. 整体状态判定
    overall = "healthy"
    if any(c["status"] == "unhealthy" for c in components.values()):
        overall = "degraded"

    return {
        "status": overall,
        "components": components,
        "version": _APP_VERSION,
        "commit": _APP_COMMIT,
    }


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
from src.source_candidates.api.routes import router as source_candidates_router
from src.subjects.api.routes import router as subjects_router

app.include_router(subjects_router)
app.include_router(source_candidates_router)

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

from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

web_dir = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.exists(web_dir):
    # 挂载静态资源目录
    assets_dir = os.path.join(web_dir, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    # 创建 SPA 中间件
    class SPAMiddleware(BaseHTTPMiddleware):
        """SPA 前端中间件 - 为非 API 路径返回 index.html"""

        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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


def main() -> None:
    """主函数 - 用于开发服务器启动。"""
    import uvicorn

    from src.config import get_settings

    settings = get_settings()

    uvicorn.run(
        "src.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
