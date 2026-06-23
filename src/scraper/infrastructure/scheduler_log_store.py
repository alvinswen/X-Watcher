"""SchedulerLogStore 契约(3 方法)。两实现共享:oracle(vendored 旧 repo)与文件 candidate。

write_log 统一为 async(carve-out):旧版是静态同步 SchedulerExecutionLogSyncWriter.write_log,本片数据层
parity 以 async 插入语义对账;应用层 sync/APScheduler 线程桥接属 M-5 接活,不在本片。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog


@runtime_checkable
class SchedulerLogStore(Protocol):
    async def get_recent_logs(
        self,
        limit: int = 50,
        event_type: SchedulerEventType | None = None,
        since: datetime | None = None,
    ) -> list[SchedulerExecutionLog]: ...
    async def cleanup_old_logs(self, retention_days: int = 30) -> int: ...
    async def write_log(self, log: SchedulerExecutionLog) -> None: ...
