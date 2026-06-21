"""schedule 单元迁移:scraper_schedule_config(单行)→ FileScheduleStore.seed。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.database.models import ScraperScheduleConfig as ScheduleOrm
from src.preference.domain.models import ScraperScheduleConfig
from src.preference.infrastructure.file_schedule_repository import FileScheduleStore


def _to_domain(o: ScheduleOrm) -> ScraperScheduleConfig:
    return ScraperScheduleConfig(
        id=o.id,
        interval_seconds=o.interval_seconds,
        next_run_time=naive(o.next_run_time),
        is_enabled=o.is_enabled,
        updated_at=naive(o.updated_at),
        updated_by=o.updated_by,
    )


@register("schedule")
async def migrate_schedule(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(ScheduleOrm))).scalars().all()
    rep = MigrationReport(entity="schedule", pg_count=len(rows))
    store = FileScheduleStore(data_root)
    store._path.unlink(missing_ok=True)            # 先清(幂等)
    if not rows:
        rep.written = rep.validated = 0
        return rep
    cfg = _to_domain(rows[0])
    await store.seed(cfg)
    rep.written = 1
    # 校验:读回 vs pg 源 domain 逐字段
    back = await store.get_schedule_config()
    if back is not None and back.model_dump() == cfg.model_dump():
        rep.validated = 1
    else:
        rep.mismatches.append(f"schedule id={cfg.id}: readback != source")
    return rep
