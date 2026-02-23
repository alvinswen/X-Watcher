"""配置验证 API 路由。

提供运行时配置验证端点，检查 LLM 提供商、Twitter API、数据库的健康状态。
"""

import asyncio
import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends

from src.summarization.llm.config import LLMProviderConfig
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.summarization.services.summarization_service import _build_providers_from_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/config", tags=["config"])


@router.get("/validate")
async def validate_config(
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict:
    """验证当前配置的服务连通性。

    返回各服务的健康状态：
    - llm_providers: 各 LLM 提供商状态
    - twitter_api: Twitter API 状态
    - database: 数据库连接状态
    """
    llm_results, twitter_result, db_result = await asyncio.gather(
        _check_llm_providers(),
        _check_twitter_api(),
        _check_database(),
    )

    return {
        "llm_providers": llm_results,
        "twitter_api": twitter_result,
        "database": db_result,
    }


async def _check_llm_providers() -> list[dict]:
    """检查已配置的 LLM 提供商连通性。"""
    try:
        config = LLMProviderConfig.from_env()
        providers = _build_providers_from_config(config)
    except Exception as e:
        logger.warning(f"LLM 配置加载失败: {e}")
        return [{"name": "config_error", "status": "unhealthy", "error": str(e)}]

    tasks = [_check_single_provider(p) for p in providers]
    return list(await asyncio.gather(*tasks))


async def _check_single_provider(provider) -> dict:
    """检查单个 LLM 提供商连通性。"""
    name = provider.get_provider_name()
    model = provider.get_model_name()
    try:
        start = time.monotonic()
        result = await asyncio.wait_for(
            provider.complete("Say OK", max_tokens=10, temperature=0),
            timeout=15,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        # 检查 Result 类型
        if hasattr(result, "value_or"):
            response = result.value_or(None)
            if response is None:
                # Failure case
                failure = result.failure()
                return {
                    "name": name,
                    "status": "unhealthy",
                    "model": model,
                    "error": str(failure),
                }

        return {
            "name": name,
            "status": "healthy",
            "model": model,
            "latency_ms": latency_ms,
        }
    except asyncio.TimeoutError:
        return {
            "name": name,
            "status": "unhealthy",
            "model": model,
            "error": "请求超时 (>15s)",
        }
    except Exception as e:
        return {
            "name": name,
            "status": "unhealthy",
            "model": model,
            "error": str(e)[:200],
        }


async def _check_twitter_api() -> dict:
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


async def _check_database() -> dict:
    """检查数据库连接。"""
    try:
        from sqlalchemy import text

        from src.database.async_session import get_async_session_maker

        session_maker = get_async_session_maker()
        start = time.monotonic()
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:200]}
