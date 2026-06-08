"""follows 单元迁移:scraper_follows → FileFollowStore.seed。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.database.models import ScraperFollow as FollowOrm
from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.file_follow_repository import FileFollowStore


def _to_domain(o: FollowOrm) -> ScraperFollow:
    # 字段以 ScraperFollow 域模型(preference.domain.models)为准:
    # 域有 backfill_status(默认 pending);域/ORM 均无 last_tweet_id(计划范式有误,以源码为准)。
    return ScraperFollow(
        id=o.id,
        username=o.username,
        added_at=naive(o.added_at),
        reason=o.reason,
        added_by=o.added_by,
        is_active=o.is_active,
        manual_limit=o.manual_limit,
        platform_user_id=o.platform_user_id,
        brief_intro=o.brief_intro,
        backfill_status=o.backfill_status,
        backfill_completed_at=naive(o.backfill_completed_at),
    )


@register("follows")
async def migrate_follows(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(FollowOrm))).scalars().all()
    rep = MigrationReport(entity="follows", pg_count=len(rows))
    store = FileFollowStore(data_root)
    store._path.unlink(missing_ok=True)
    domains = [_to_domain(o) for o in rows]
    await store.seed(domains)
    rep.written = len(domains)
    back = {f.id: f for f in await store.get_all_follows(include_inactive=True)}
    src = {f.id: f for f in domains}
    rep.validated = 0
    for fid, sd in src.items():
        bd = back.get(fid)
        if bd is not None and bd.model_dump() == sd.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"follows id={fid}: readback != source")
    return rep
