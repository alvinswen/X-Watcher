"""TwitterAPI.io 账户信息缓存服务。

提供进程内 TTL 缓存的余额查询能力，避免每次前端请求都触发外部 API 调用。
缓存默认 10 分钟有效，过期后自动刷新；外部接口失败时返回上一次成功的快照
并标记 ``source="stale"``。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone, UTC
from typing import Any

from returns.result import Failure

from src.scraper.client import TwitterClient

logger = logging.getLogger(__name__)


class AccountInfoService:
    """带 TTL 缓存的账户余额服务。

    单实例长期持有同一个 ``TwitterClient``，通过 ``asyncio.Lock`` 防止并发刷新
    导致重复消耗外部接口配额。
    """

    CACHE_TTL_SECONDS = 600  # 10 分钟

    def __init__(self, client: TwitterClient) -> None:
        self._client = client
        self._cached_credits: int | None = None
        self._cached_at: datetime | None = None
        self._lock = asyncio.Lock()

    def _is_fresh(self) -> bool:
        if self._cached_at is None:
            return False
        return datetime.now(UTC) - self._cached_at < timedelta(
            seconds=self.CACHE_TTL_SECONDS
        )

    async def get_balance(self, force_refresh: bool = False) -> dict[str, Any]:
        """返回账户余额状态。

        Args:
            force_refresh: 忽略缓存强制查询外部接口

        Returns:
            dict 含字段:
                - recharge_credits: int | None
                - fetched_at: datetime | None (UTC)
                - source: "live" | "cache" | "stale" | "error"
                - error: str | None (仅当外部调用失败时存在)
        """
        async with self._lock:
            if not force_refresh and self._is_fresh():
                return {
                    "recharge_credits": self._cached_credits,
                    "fetched_at": self._cached_at,
                    "source": "cache",
                    "error": None,
                }

            result = await self._client.fetch_account_info()
            if not isinstance(result, Failure):
                payload = result.unwrap()
                credits = payload.get("recharge_credits")
                if isinstance(credits, int):
                    self._cached_credits = credits
                    self._cached_at = datetime.now(UTC)
                    return {
                        "recharge_credits": credits,
                        "fetched_at": self._cached_at,
                        "source": "live",
                        "error": None,
                    }
                logger.warning(
                    "fetch_account_info 返回了非整数 recharge_credits: %r", credits
                )
                error_msg = f"响应缺少有效 recharge_credits 字段: {payload!r}"
            else:
                error_msg = result.failure().message

            # 外部调用失败：若有历史快照则降级返回 stale，否则返回 error
            if self._cached_credits is not None and self._cached_at is not None:
                return {
                    "recharge_credits": self._cached_credits,
                    "fetched_at": self._cached_at,
                    "source": "stale",
                    "error": error_msg,
                }
            return {
                "recharge_credits": None,
                "fetched_at": None,
                "source": "error",
                "error": error_msg,
            }


_service_instance: AccountInfoService | None = None


def get_account_info_service() -> AccountInfoService:
    """获取进程级单例。

    懒加载以确保 ``Settings`` 和 ``TwitterClient`` 在请求路径上初始化，
    避免模块导入期就触发配置读取。
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = AccountInfoService(TwitterClient())
    return _service_instance


def reset_account_info_service() -> None:
    """清除单例（仅供测试使用）。"""
    global _service_instance
    _service_instance = None
