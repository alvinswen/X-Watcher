"""Prometheus 监控路由。

提供 /metrics 端点供 Prometheus 抓取监控指标。
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.config import get_settings

router = APIRouter(tags=["monitoring"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus 监控指标端点。

    返回 Prometheus 文本格式的监控指标。

    Returns:
        Response: 包含 Prometheus 格式指标数据的响应
    """
    settings = get_settings()

    # 检查是否启用监控
    if not getattr(settings, "prometheus_enabled", True):
        return Response(
            content=b"# Monitoring is disabled\n",
            media_type=CONTENT_TYPE_LATEST,
        )

    # 生成指标数据
    data = generate_latest()

    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
    )
