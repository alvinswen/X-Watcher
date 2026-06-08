"""scheduler-log 单元迁移:scheduler_execution_log → FileSchedulerLogStore.seed。

注意:
- store.seed 按 seq 重新分配 id(1..N),id 是存储侧 surrogate(域 id: int|None);
  故校验逐字段比对时排除 id(content 忠实即可,id 非业务键)。
- pg 通常 0 行 → pg=written=validated=0 自然 OK。
- executed_at/next_run_time 是 DateTime(timezone=True)=aware → naive()。
- event_type ORM 存 str,域是 SchedulerEventType(str Enum),pydantic 自动 coerce。
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.scraper.domain.scheduler_log import SchedulerExecutionLog
from src.scraper.infrastructure.file_scheduler_log_repository import FileSchedulerLogStore
from src.scraper.infrastructure.scheduler_log_models import SchedulerExecutionLogOrm


def _to_domain(o: SchedulerExecutionLogOrm) -> SchedulerExecutionLog:
    return SchedulerExecutionLog(
        id=o.id,
        job_id=o.job_id,
        event_type=o.event_type,
        executed_at=naive(o.executed_at),
        duration_seconds=o.duration_seconds,
        error_type=o.error_type,
        error_message=o.error_message,
        next_run_time=naive(o.next_run_time),
    )


def _content_key(rec: SchedulerExecutionLog) -> str:
    d = rec.model_dump(mode="json")
    d.pop("id", None)  # id 由 store 重分配,非业务键
    return json.dumps(d, sort_keys=True)


@register("scheduler_log")
async def migrate_scheduler_log(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(SchedulerExecutionLogOrm))).scalars().all()
    rep = MigrationReport(entity="scheduler_log", pg_count=len(rows))
    rep.dropped_columns = ["created_at"]  # DB audit 时间戳,域模型无(诚实标注;pg 现 0 行)
    store = FileSchedulerLogStore(data_root)
    store._path.unlink(missing_ok=True)
    domains = [_to_domain(o) for o in rows]
    await store.seed(domains)
    rep.written = len(domains)
    back = await store.get_recent_logs(limit=10**9)
    back_keys = [_content_key(b) for b in back]
    rep.validated = 0
    for sd in domains:
        k = _content_key(sd)
        if k in back_keys:
            back_keys.remove(k)  # 消费一个,防重复计数
            rep.validated += 1
        else:
            rep.mismatches.append(f"scheduler_log job_id={sd.job_id}@{sd.executed_at}: readback content missing")
    return rep
