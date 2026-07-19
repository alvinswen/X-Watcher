"""Prometheus 监控中间件。

记录 HTTP 请求的计数和延迟指标。
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.monitoring import metrics


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Prometheus 监控中间件。

    自动记录所有 HTTP 请求的计数和延迟。
    """

    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: list[str] | None = None,
    ) -> None:
        """初始化中间件。

        Args:
            app: ASGI 应用
            excluded_paths: 排除监控的路径列表
        """
        super().__init__(app)
        self.excluded_paths = set(excluded_paths or ["/metrics"])

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """处理请求并记录指标。

        Args:
            request: HTTP 请求
            call_next: 下一个中间件或路由处理器

        Returns:
            Response: HTTP 响应
        """
        # 跳过排除的路径
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # 记录开始时间
        start_time = time.time()

        # 处理请求
        response = await call_next(request)

        # 计算请求持续时间
        duration = time.time() - start_time

        # 路由匹配已在 call_next 后完成，使用框架模板控制标签基数。
        path = self._label_path(request)

        # 更新指标
        metrics.http_requests_total.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()

        metrics.http_request_duration_seconds.labels(
            method=request.method,
            path=path,
        ).observe(duration)

        return response

    def _label_path(self, request: Request) -> str:
        """返回框架匹配后的路由模板；未匹配请求使用固定标签。"""
        route = request.scope.get("route")
        path_format = getattr(route, "path_format", None)
        return path_format if isinstance(path_format, str) else "__unmatched__"
