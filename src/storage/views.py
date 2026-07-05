"""by-day 派生视图维护与读取。

权威源 = data/tweets/<author>/<YYYY-MM>.jsonl;派生 = data/_views/by-day/<YYYY-MM-DD>.jsonl。
派生去规范化存全记录,可从权威源一键重建,永不作为裁决依据(T-VIEW-001)。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.storage import paths
from src.storage.atomic import shard_lock
from src.storage.jsonl_store import read_shard, upsert, write_shard


def _utc_date_of(record: dict[str, Any]) -> date:
    return paths.as_utc(datetime.fromisoformat(record["created_at"])).date()


async def by_day_upsert(data_root: Path, records: list[dict[str, Any]]) -> None:
    """把记录按 UTC 日分组,增量 upsert 进 by-day 视图(原子 + 分片锁)。"""
    groups: dict[date, list[dict[str, Any]]] = {}
    for rec in records:
        groups.setdefault(_utc_date_of(rec), []).append(rec)
    for utc_date, recs in groups.items():
        shard = paths.by_day_shard(data_root, utc_date)
        async with shard_lock(shard):
            upsert(shard, recs, key="tweet_id")


def rebuild_by_day(data_root: Path) -> None:
    """清空 by-day 视图 → 全量扫 canonical → 重写。启动重建/运维兜底用(同步)。"""
    for shard in paths.iter_by_day_shards(data_root):
        shard.unlink()
    groups: dict[date, list[dict[str, Any]]] = {}
    for shard in paths.iter_canonical_shards(data_root):
        for rec in read_shard(shard):
            groups.setdefault(_utc_date_of(rec), []).append(rec)
    for utc_date, recs in groups.items():
        write_shard(paths.by_day_shard(data_root, utc_date), recs)


def read_by_day_dates(data_root: Path, utc_dates: list[date]) -> list[dict[str, Any]]:
    """读给定 UTC 日列表的分片原始记录。缺失分片静默跳过；可能含窗口外记录，细过滤交调用方。"""
    out: list[dict[str, Any]] = []
    for d in utc_dates:
        out.extend(read_shard(paths.by_day_shard(data_root, d)))
    return out


def read_by_day_range(data_root: Path, since: datetime, until: datetime) -> list[dict[str, Any]]:
    """读 [since, until) 覆盖的 by-day 分片(按文件名日期过滤现有分片,不枚举日历)。

    返回的是分片级粗读结果(可能含窗口外记录),细粒度 created_at 过滤由调用方做。
    """
    since_d = paths.as_utc(since).date()
    last_d = (paths.as_utc(until) - timedelta(microseconds=1)).date()
    out: list[dict[str, Any]] = []
    for shard in paths.iter_by_day_shards(data_root):
        sd = date.fromisoformat(shard.stem)
        if since_d <= sd <= last_d:
            out.extend(read_shard(shard))
    return out


def reconcile_by_day(data_root: Path) -> tuple[bool, dict[str, Any]]:
    """校验 by-day 视图与 canonical 一一对应(集合 + 内容 + 归档日正确)。"""
    canonical: dict[str, dict[str, Any]] = {}
    for shard in paths.iter_canonical_shards(data_root):
        for rec in read_shard(shard):
            canonical[rec["tweet_id"]] = rec
    view: dict[str, dict[str, Any]] = {}
    misplaced: list[dict[str, Any]] = []
    for shard in paths.iter_by_day_shards(data_root):
        sd = date.fromisoformat(shard.stem)
        for rec in read_shard(shard):
            view[rec["tweet_id"]] = rec
            rec_date = _utc_date_of(rec)
            if rec_date != sd:
                misplaced.append({"tweet_id": rec["tweet_id"], "shard": sd.isoformat(),
                                  "actual": rec_date.isoformat()})
    only_canonical = sorted(set(canonical) - set(view))
    only_view = sorted(set(view) - set(canonical))
    content_mismatch = sorted(tid for tid in (set(canonical) & set(view)) if canonical[tid] != view[tid])
    ok = not (only_canonical or only_view or content_mismatch or misplaced)
    return ok, {
        "canonical_count": len(canonical), "view_count": len(view),
        "only_canonical": only_canonical, "only_view": only_view,
        "content_mismatch": content_mismatch, "misplaced": misplaced,
    }
