"""fetch-stats 单元迁移:scraper_fetch_stats → FileFetchStatsStore.seed。

dropped_columns:created_at/updated_at(DB audit 时间戳,域无)。
注意:last_fetch_at 是 DateTime(timezone=True)=aware → naive() 必须。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.scraper.domain.fetch_stats import FetchStats
from src.scraper.infrastructure.fetch_stats_models import FetchStatsOrm
from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore


def _to_domain(o: FetchStatsOrm) -> FetchStats:
    return FetchStats(
        username=o.username,
        last_fetch_at=naive(o.last_fetch_at),
        last_fetched_count=o.last_fetched_count,
        last_new_count=o.last_new_count,
        total_fetches=o.total_fetches,
        avg_new_rate=o.avg_new_rate,
        consecutive_empty_fetches=o.consecutive_empty_fetches,
    )


@register("fetch_stats")
async def migrate_fetch_stats(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(FetchStatsOrm))).scalars().all()
    rep = MigrationReport(entity="fetch_stats", pg_count=len(rows))
    rep.dropped_columns = ["created_at", "updated_at"]
    store = FileFetchStatsStore(data_root)
    store._path.unlink(missing_ok=True)
    domains = [_to_domain(o) for o in rows]
    await store.seed(domains)
    rep.written = len(domains)
    rep.validated = 0
    for sd in domains:
        bd = await store.get_stats(sd.username)
        if bd is not None and bd.model_dump() == sd.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"fetch_stats username={sd.username}: readback != source")
    return rep
