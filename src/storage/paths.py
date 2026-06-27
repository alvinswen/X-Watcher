"""唯一分片路径规则。所有路径约定集中于此。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def canonical_shard(data_root: Path, author_username: str, created_at: datetime) -> Path:
    month = as_utc(created_at).strftime("%Y-%m")
    return Path(data_root) / "tweets" / author_username.lower() / f"{month}.jsonl"


def author_shards(data_root: Path, author_username: str) -> list[Path]:
    base = Path(data_root) / "tweets" / author_username.lower()
    if not base.exists():
        return []
    return sorted(base.glob("*.jsonl"))


def iter_canonical_shards(data_root: Path) -> list[Path]:
    base = Path(data_root) / "tweets"
    if not base.exists():
        return []
    return sorted(base.glob("*/*.jsonl"))


def by_day_shard(data_root: Path, utc_date: date) -> Path:
    return Path(data_root) / "_views" / "by-day" / f"{utc_date.isoformat()}.jsonl"


def iter_by_day_shards(data_root: Path) -> list[Path]:
    base = Path(data_root) / "_views" / "by-day"
    if not base.exists():
        return []
    return sorted(base.glob("*.jsonl"))


def local_day_to_utc_window(local_date: date, tz_offset_min: int) -> tuple[datetime, datetime]:
    """本地某天 + tz_offset → [utc_start, utc_end) 24h 窗口(对齐旧 _local_date_to_utc_range)。

    tz_offset_min = JS getTimezoneOffset()(分钟);local + offset = UTC。
    """
    local_midnight = datetime(local_date.year, local_date.month, local_date.day)
    utc_start = (local_midnight + timedelta(minutes=tz_offset_min)).replace(tzinfo=timezone.utc)
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
    return Path(data_root) / "subjects" / f"{subject_id}.json"


def subject_index(data_root: Path) -> Path:
    return Path(data_root) / "subjects" / "index.json"


def subject_match_shard(data_root: Path, subject_id: str, matched_at: datetime) -> Path:
    month = as_utc(matched_at).strftime("%Y-%m")
    return Path(data_root) / "subjects" / subject_id / "matches" / f"{month}.jsonl"


def subject_digest_doc(data_root: Path, subject_id: str, hour: str) -> Path:
    return Path(data_root) / "subjects" / subject_id / "digests" / f"{hour}.json"
