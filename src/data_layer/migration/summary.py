"""summary 单元迁移:summaries(42K)→ FileSummaryStore.seed。

注意:created_at/updated_at 是 DateTime(timezone=True)=aware → naive()。
域 SummaryRecord 15 字段 == ORM 15 列(无 DB-only 多余列,无 dropped_columns)。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.summarization.infrastructure.models import SummaryOrm


def _to_domain(o: SummaryOrm) -> SummaryRecord:
    return SummaryRecord(
        summary_id=o.summary_id,
        tweet_id=o.tweet_id,
        summary_text=o.summary_text,
        translation_text=o.translation_text,
        model_provider=o.model_provider,
        model_name=o.model_name,
        prompt_tokens=o.prompt_tokens,
        completion_tokens=o.completion_tokens,
        total_tokens=o.total_tokens,
        cost_usd=o.cost_usd,
        cached=o.cached,
        is_generated_summary=o.is_generated_summary,
        content_hash=o.content_hash,
        created_at=naive(o.created_at),
        updated_at=naive(o.updated_at),
    )


@register("summary")
async def migrate_summary(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(SummaryOrm))).scalars().all()
    rep = MigrationReport(entity="summary", pg_count=len(rows))
    store = FileSummaryStore(data_root)
    store._path.unlink(missing_ok=True)
    domains = [_to_domain(o) for o in rows]
    await store.seed(domains)
    rep.written = len(domains)
    back = {s.summary_id: s for s in await store.get_all_summaries()}
    src = {s.summary_id: s for s in domains}
    rep.validated = 0
    for sid, sd in src.items():
        bd = back.get(sid)
        if bd is not None and bd.model_dump() == sd.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"summary summary_id={sid}: readback != source")
    return rep
