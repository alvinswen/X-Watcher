"""Prometheus 监控中间件。

记录 HTTP 请求的计数和延迟指标。
"""

import time
from typing import Callable

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
        call_next: Callable,
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

        # 获取请求路径（标准化，去除动态路径参数）
        path = self._normalize_path(request.url.path)

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

    def _normalize_path(self, path: str) -> str:
        """标准化请求路径。

        将动态路径参数替换为占位符，如 /api/admin/scrape/abc123 -> /api/admin/scrape/{task_id}

        Args:
            path: 原始路径

        Returns:
            str: 标准化后的路径
        """
        # 定义需要标准化的路径模式
        patterns = [
            ("/api/admin/scrape/", "/api/admin/scrape/{task_id}"),
            ("/api/deduplicate/groups/", "/api/deduplicate/groups/{group_id}"),
            ("/api/deduplicate/tweets/", "/api/deduplicate/tweets/{tweet_id}"),
            ("/api/deduplicate/tasks/", "/api/deduplicate/tasks/{task_id}"),
            ("/api/summaries/tweets/", "/api/summaries/tweets/{tweet_id}"),
            ("/api/summaries/tasks/", "/api/summaries/tasks/{task_id}"),
        ]

        for prefix, replacement in patterns:
            if path.startswith(prefix) and len(path) > len(prefix):
                return replacement

        return path
