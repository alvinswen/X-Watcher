# src/summarization/infrastructure/summary_store.py
"""SummaryStore 契约(5 方法)+ 异常。两实现共享:oracle(vendored 旧 repo)与文件 candidate。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.summarization.domain.models import CostStats, SummaryRecord


class RepositoryError(Exception):
    """仓库操作错误。"""


class NotFoundError(RepositoryError):
    """资源未找到错误(delete_summary 不存在时抛,非返回 False)。"""


@runtime_checkable
class SummaryStore(Protocol):
    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord: ...
    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None: ...
    async def get_cost_stats(self, start_date: datetime | None = None,
                             end_date: datetime | None = None) -> CostStats: ...
    async def delete_summary(self, summary_id: str) -> bool: ...
    async def find_by_content_hash(self, content_hash: str) -> SummaryRecord | None: ...
