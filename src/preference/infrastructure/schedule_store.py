"""ScheduleStore 契约(2 方法)+ 异常。两实现共享:oracle(vendored 旧 repo)与文件 candidate。

注:schedule 两方法无可观测错误面(get 走 PK 单行不会多行、upsert 无 try/except),
RepositoryError 仅作模块约定保留(对齐 follows/profile),无 parity case 触发它(诚实标注)。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.preference.domain.models import ScraperScheduleConfig


class RepositoryError(Exception):
    """仓库操作错误。"""


@runtime_checkable
class ScheduleStore(Protocol):
    async def get_schedule_config(self) -> ScraperScheduleConfig | None: ...
    async def upsert_schedule_config(
        self,
        interval_seconds: int | None = None,
        next_run_time: datetime | None = None,
        is_enabled: bool | None = None,
        updated_by: str = "",
    ) -> ScraperScheduleConfig: ...
