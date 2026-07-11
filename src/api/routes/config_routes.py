"""配置验证 API 路由。

提供运行时配置验证端点，检查 Twitter API、数据库的健康状态。
"""

import asyncio
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

router = APIRouter(prefix="/api/admin/config", tags=["config"])


@router.get("/validate")
async def validate_config(
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """验证当前配置的服务连通性。

    返回各服务的健康状态：
    - twitter_api: Twitter API 状态
    - database: 数据库连接状态
    """
    twitter_result, db_result = await asyncio.gather(
        _check_twitter_api(),
        _check_database(),
    )

    return {
        "twitter_api": twitter_result,
        "database": db_result,
    }


async def _check_twitter_api() -> dict[str, Any]:
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
        else:
            return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:200]}


async def _check_database() -> dict[str, Any]:
    """检查数据库连接。"""
    from src.data_layer.provider import data_root

    # file 模式(pg 下线守卫):不连 pg,改探数据目录存在性
    root = data_root()
    if root.exists():
        return {"status": "healthy", "mode": "file", "data_root": str(root)}
    return {"status": "unhealthy", "error": f"data_root 不存在: {root}"}
