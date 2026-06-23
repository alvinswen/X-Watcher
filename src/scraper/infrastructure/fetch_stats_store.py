"""FetchStatsStore 契约(3 方法)。两实现共享:oracle(vendored 旧 repo)与文件 candidate。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.scraper.domain.fetch_stats import FetchStats


@runtime_checkable
class FetchStatsStore(Protocol):
    async def get_stats(self, username: str) -> FetchStats | None: ...
    async def batch_get_stats(self, usernames: list[str]) -> dict[str, FetchStats]: ...
    async def upsert_stats(self, stats: FetchStats) -> None: ...
