"""配置连通性检查共享实现。"""

import os
import time
from typing import Any

import httpx


async def check_twitter_api() -> dict[str, Any]:
    """检查 Twitter API 连通性。"""
    api_key = os.getenv("TWITTER_API_KEY", "")
    base_url = os.getenv("TWITTER_BASE_URL", "https://api.twitterapi.io/twitter")

    if not api_key:
        return {"status": "unhealthy", "error": "TWITTER_API_KEY 未配置"}

    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base_url}/user/info",
                params={"userName": "twitter"},
                headers={"X-API-Key": api_key},
            )
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            return {"status": "healthy", "latency_ms": latency_ms}
        return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:200]}


def check_database() -> dict[str, Any]:
    """检查文件数据目录是否可用。"""
    from src.data_layer.provider import data_root

    root = data_root()
    if root.exists():
        return {"status": "healthy", "mode": "file", "data_root": str(root)}
    return {"status": "unhealthy", "error": f"data_root 不存在: {root}"}
