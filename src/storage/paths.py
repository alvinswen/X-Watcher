"""唯一分片路径规则。所有路径约定集中于此。"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def _guard(data_root: Path, target: Path) -> Path:
    root_n = Path(os.path.normpath(Path(data_root)))
    target_n = Path(os.path.normpath(target))
    if not target_n.is_relative_to(root_n):
        raise ValueError(f"路径越界: 目标不在数据根目录内(root={root_n})")
    return target


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def canonical_shard(data_root: Path, author_username: str, created_at: datetime) -> Path:
    month = as_utc(created_at).strftime("%Y-%m")
    target = Path(data_root) / "tweets" / author_username.lower() / f"{month}.jsonl"
    return _guard(data_root, target)


def author_shards(data_root: Path, author_username: str) -> list[Path]:
    base = _guard(data_root, Path(data_root) / "tweets" / author_username.lower())
    if not base.exists():
        return []
    return sorted(base.glob("*.jsonl"))


def iter_canonical_shards(data_root: Path) -> list[Path]:
    base = _guard(data_root, Path(data_root) / "tweets")
    if not base.exists():
        return []
    return sorted(base.glob("*/*.jsonl"))


def by_day_shard(data_root: Path, utc_date: date) -> Path:
    target = Path(data_root) / "_views" / "by-day" / f"{utc_date.isoformat()}.jsonl"
    return _guard(data_root, target)


def iter_by_day_shards(data_root: Path) -> list[Path]:
    base = _guard(data_root, Path(data_root) / "_views" / "by-day")
    if not base.exists():
        return []
    return sorted(base.glob("*.jsonl"))


def local_day_to_utc_window(local_date: date, tz_offset_min: int) -> tuple[datetime, datetime]:
    """本地某天 + tz_offset → [utc_start, utc_end) 24h 窗口(对齐旧 _local_date_to_utc_range)。

    tz_offset_min = JS getTimezoneOffset()(分钟);local + offset = UTC。
    """
    local_midnight = datetime(local_date.year, local_date.month, local_date.day)
    utc_start = (local_midnight + timedelta(minutes=tz_offset_min)).replace(tzinfo=UTC)
    utc_end = utc_start + timedelta(days=1)
    return utc_start, utc_end


def utc_dates_in_window(utc_start: datetime, utc_end: datetime) -> list[date]:
    """[utc_start, utc_end) 覆盖的 UTC 日历日(1–2 个)。"""
    dates: list[date] = []
    d = utc_start.date()
    last = (utc_end - timedelta(microseconds=1)).date()
    while d <= last:
        dates.append(d)
        d = d + timedelta(days=1)
    return dates


def subject_doc(data_root: Path, subject_id: str) -> Path:
    target = Path(data_root) / "subjects" / f"{subject_id}.json"
    return _guard(data_root, target)


def subject_index(data_root: Path) -> Path:
    target = Path(data_root) / "subjects" / "index.json"
    return _guard(data_root, target)


def subject_match_shard(data_root: Path, subject_id: str, matched_at: datetime) -> Path:
    month = as_utc(matched_at).strftime("%Y-%m")
    target = Path(data_root) / "subjects" / subject_id / "matches" / f"{month}.jsonl"
    return _guard(data_root, target)


def subject_digest_shard(data_root: Path, subject_id: str, interval_start: datetime) -> Path:
    month = as_utc(interval_start).strftime("%Y-%m")
    target = Path(data_root) / "subjects" / subject_id / "digests" / f"{month}.jsonl"
    return _guard(data_root, target)


def subject_feedback_shard(data_root: Path, subject_id: str, when: datetime) -> Path:
    month = as_utc(when).strftime("%Y-%m")
    target = Path(data_root) / "subjects" / subject_id / "feedback" / f"{month}.jsonl"
    return _guard(data_root, target)


def subject_eval_shard(data_root: Path, subject_id: str, when: datetime) -> Path:
    month = as_utc(when).strftime("%Y-%m")
    target = Path(data_root) / "subjects" / subject_id / "eval" / f"{month}.jsonl"
    return _guard(data_root, target)


def subject_review_doc(data_root: Path, subject_id: str) -> Path:
    target = Path(data_root) / "subjects" / subject_id / "review" / "latest.json"
    return _guard(data_root, target)


def subject_review_history_doc(data_root: Path, subject_id: str, version: int) -> Path:
    target = (
        Path(data_root) / "subjects" / subject_id / "review" / "history" / f"{version}.json"
    )
    return _guard(data_root, target)


def subject_provenance_doc(data_root: Path, subject_id: str, kind: str, key: str) -> Path:
    if kind not in {"matches", "digests", "review"}:
        raise ValueError("provenance kind 只能是 matches、digests 或 review")
    target = Path(data_root) / "subjects" / subject_id / "provenance" / kind / f"{key}.json"
    return _guard(data_root, target)


def summary_shard(data_root: Path, created_at: datetime) -> Path:
    month = as_utc(created_at).strftime("%Y-%m")
    target = Path(data_root) / "summaries" / f"{month}.jsonl"
    return _guard(data_root, target)


def iter_summary_shards(data_root: Path) -> list[Path]:
    base = _guard(data_root, Path(data_root) / "summaries")
    if not base.exists():
        return []
    return sorted(base.glob("*.jsonl"))


def summary_legacy_doc(data_root: Path) -> Path:
    target = Path(data_root) / "summaries" / "summaries.json"
    return _guard(data_root, target)


def subject_dir(data_root: Path, subject_id: str) -> Path:
    target = Path(data_root) / "subjects" / subject_id
    return _guard(data_root, target)


def source_candidate_doc(data_root: Path, candidate_id: str) -> Path:
    target = Path(data_root) / "source_candidates" / f"{candidate_id}.json"
    return _guard(data_root, target)


def source_candidate_index(data_root: Path) -> Path:
    target = Path(data_root) / "source_candidates" / "index.json"
    return _guard(data_root, target)


def iter_source_candidate_docs(data_root: Path) -> list[Path]:
    base = _guard(data_root, Path(data_root) / "source_candidates")
    if not base.exists():
        return []
    return sorted(path for path in base.glob("*.json") if path.name != "index.json")


def scrape_group_state_doc(data_root: Path) -> Path:
    target = Path(data_root) / "scrape_state" / "groups.json"
    return _guard(data_root, target)
