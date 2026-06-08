"""profile 单元迁移:x_user_profiles → FileProfileStore.seed。

dropped_columns(文件层设计性不存,诚实标注):
- raw_json:完整 API 响应 blob(文件层不存)
- created_at/updated_at:DB 行级 audit 时间戳(域模型无,与 tweet db_* 一致处理)
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.database.x_user_profile_model import XUserProfileOrm
from src.preference.domain.models import XUserProfile
from src.preference.infrastructure.file_profile_repository import FileProfileStore


def _to_domain(o: XUserProfileOrm) -> XUserProfile:
    return XUserProfile(
        platform_user_id=o.platform_user_id,
        username=o.username,
        display_name=o.display_name,
        is_blue_verified=o.is_blue_verified,
        verified_type=o.verified_type,
        profile_picture=o.profile_picture,
        cover_picture=o.cover_picture,
        description=o.description,
        location=o.location,
        followers_count=o.followers_count,
        following_count=o.following_count,
        statuses_count=o.statuses_count,
        favourites_count=o.favourites_count,
        media_count=o.media_count,
        account_created_at=o.account_created_at,
        is_automated=o.is_automated,
        possibly_sensitive=o.possibly_sensitive,
        pinned_tweet_ids=o.pinned_tweet_ids,
        unavailable=o.unavailable,
        unavailable_reason=o.unavailable_reason,
        fetched_at=naive(o.fetched_at),
    )


@register("profile")
async def migrate_profile(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(XUserProfileOrm))).scalars().all()
    rep = MigrationReport(entity="profile", pg_count=len(rows))
    rep.dropped_columns = ["raw_json", "created_at", "updated_at"]
    store = FileProfileStore(data_root)
    store._path.unlink(missing_ok=True)
    domains = [_to_domain(o) for o in rows]
    await store.seed(domains)
    rep.written = len(domains)
    back = {p.platform_user_id: p for p in await store.get_all_profiles()}
    src = {p.platform_user_id: p for p in domains}
    rep.validated = 0
    for pid, sd in src.items():
        bd = back.get(pid)
        if bd is not None and bd.model_dump() == sd.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"profile id={pid}: readback != source")
    return rep
