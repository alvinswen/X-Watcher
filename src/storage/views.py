"""by-day 派生视图维护与读取。

权威源 = data/tweets/<author>/<YYYY-MM>.jsonl;派生 = data/_views/by-day/<YYYY-MM-DD>.jsonl。
派生去规范化存全记录,可从权威源一键重建,永不作为裁决依据(T-VIEW-001)。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.storage import paths
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.storage.jsonl_store import read_shard, upsert, write_shard

logger = logging.getLogger(__name__)

_STATE_VERSION = 1
_Fingerprint = tuple[tuple[str, int, int], ...]


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


def _fingerprint(data_root: Path, shards: list[Path]) -> _Fingerprint:
    """分片现场指纹:(相对路径, mtime_ns, size) 排序元组。"""
    entries: list[tuple[str, int, int]] = []
    for shard in shards:
        try:
            stat = shard.stat()
        except FileNotFoundError:
            continue
        entries.append((str(shard.relative_to(data_root)), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


def _shard_date(shard: Path) -> date | None:
    """by-day 分片文件名 → UTC 日；文件名不是合法日期(误入的杂项 .jsonl)返回 None,按幽灵清理。"""
    try:
        return date.fromisoformat(shard.stem)
    except ValueError:
        return None


def _canonical_fingerprint(data_root: Path) -> _Fingerprint:
    return _fingerprint(data_root, paths.iter_canonical_shards(data_root))


def _view_fingerprint(data_root: Path) -> _Fingerprint:
    return _fingerprint(data_root, paths.iter_by_day_shards(data_root))


def _as_fingerprint(raw: Any) -> _Fingerprint:
    return tuple(sorted((str(a), int(b), int(c)) for a, b, c in raw))


def _write_state(data_root: Path, canonical: _Fingerprint, view: _Fingerprint) -> None:
    try:
        atomic_write_doc(
            paths.by_day_state_doc(data_root),
            {
                "version": _STATE_VERSION,
                "written_at": datetime.now(UTC).isoformat(),
                "canonical": [list(item) for item in canonical],
                "view": [list(item) for item in view],
            },
        )
    except Exception:
        logger.warning("写入 by-day 现场记录失败(下次启动会多重建一次)", exc_info=True)


def rebuild_by_day(data_root: Path) -> dict[str, int]:
    """全量扫 canonical → 先删幽灵天 → 逐日原子替换 → 写现场记录。启动重建/运维兜底用(同步)。"""
    groups: dict[date, list[dict[str, Any]]] = {}
    for shard in paths.iter_canonical_shards(data_root):
        for rec in read_shard(shard):
            groups.setdefault(_utc_date_of(rec), []).append(rec)
    stale = [
        shard
        for shard in paths.iter_by_day_shards(data_root)
        if _shard_date(shard) not in groups
    ]
    for shard in stale:
        shard.unlink(missing_ok=True)
    for utc_date, recs in groups.items():
        write_shard(paths.by_day_shard(data_root, utc_date), recs)
    _write_state(data_root, _canonical_fingerprint(data_root), _view_fingerprint(data_root))
    return {"days": len(groups), "stale": len(stale)}


def _skip_reason(data_root: Path) -> str | None:
    """返回 None 表示可跳过重建;否则返回需要重建的原因。"""
    try:
        doc = read_doc(paths.by_day_state_doc(data_root))
    except Exception:
        return "现场记录读不出"
    if doc is None:
        return "现场记录缺失"
    if doc.get("version") != _STATE_VERSION:
        return "现场记录版本不认识"
    try:
        recorded_canonical = _as_fingerprint(doc["canonical"])
        recorded_view = _as_fingerprint(doc["view"])
    except Exception:
        return "现场记录读不出"
    if recorded_canonical != _canonical_fingerprint(data_root):
        return "推文正本变了"
    if recorded_view != _view_fingerprint(data_root):
        return "按天索引副本被改动"
    return None


def warm_start_by_day(data_root: Path) -> None:
    """启动时按双指纹判断是否可跳过重建;需要重建则尽力重建,失败记错但不阻断服务启动。"""
    try:
        reason = _skip_reason(data_root)
        if reason is None:
            logger.info("跳过启动重建 by-day 视图: 跳过原因=双指纹一致")
            return
        logger.info("开始启动重建 by-day 视图: 触发原因=%s", reason)
        stats = rebuild_by_day(data_root)
        logger.info(
            "完成启动重建 by-day 视图: 产出=%s 天 清理=%s 天", stats["days"], stats["stale"]
        )
    except Exception:
        logger.error("启动时重建 by-day 视图失败", exc_info=True)


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
