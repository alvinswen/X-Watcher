"""文件版 SummaryStore：按摘要创建时间写入月度 JSONL 分片。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from src.storage import paths
from src.storage.atomic import shard_lock
from src.storage.doc_store import read_doc
from src.storage.jsonl_store import read_shard, write_shard
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.summary_store import RepositoryError

logger = logging.getLogger(__name__)

_ShardSignature = tuple[tuple[str, int, int], ...]


class _SummaryLocation(NamedTuple):
    shard: Path
    summary_id: str
    tweet_id: str
    content_hash: str
    created_at: str


_Locator = tuple[
    dict[str, list[_SummaryLocation]],
    dict[str, _SummaryLocation],
]
_locator_cache: dict[str, tuple[_ShardSignature, _Locator]] = {}


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ready_summary_shards(data_root: Path) -> list[Path]:
    shards = paths.iter_summary_shards(data_root)
    if shards:
        return shards

    legacy = paths.summary_legacy_doc(data_root)
    doc = read_doc(legacy)
    legacy_count = len(doc.get("summaries", {})) if doc is not None else 0
    if legacy_count > 0:
        logger.error(
            "检测到尚未迁移的历史摘要数据，但未找到任何月份分片: data_root=%s legacy=%s",
            data_root,
            legacy,
        )
        raise RepositoryError("检测到尚未迁移的历史摘要数据，但未找到任何月份分片")
    return []


def _shard_signature(data_root: Path, shards: list[Path] | None = None) -> _ShardSignature:
    entries: list[tuple[str, int, int]] = []
    for shard in shards if shards is not None else paths.iter_summary_shards(data_root):
        try:
            stat = shard.stat()
        except FileNotFoundError:
            continue
        entries.append((str(shard.relative_to(data_root)), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


def _append_location(locator: _Locator, shard: Path, record: dict[str, Any]) -> _SummaryLocation:
    location = _SummaryLocation(
        shard=shard,
        summary_id=str(record["summary_id"]),
        tweet_id=str(record["tweet_id"]),
        content_hash=str(record["content_hash"]),
        created_at=str(record["created_at"]),
    )
    by_tweet, by_summary = locator
    by_tweet.setdefault(location.tweet_id, []).append(location)
    by_summary[location.summary_id] = location
    return location


def _remove_location(locator: _Locator, location: _SummaryLocation) -> None:
    by_tweet, by_summary = locator
    candidates = by_tweet.get(location.tweet_id, [])
    remaining = [candidate for candidate in candidates if candidate != location]
    if remaining:
        by_tweet[location.tweet_id] = remaining
    else:
        by_tweet.pop(location.tweet_id, None)
    if by_summary.get(location.summary_id) == location:
        by_summary.pop(location.summary_id, None)


def _build_locator(shards: list[Path]) -> _Locator:
    locator: _Locator = ({}, {})
    for shard in shards:
        for record in read_shard(shard):
            _append_location(locator, shard, record)
    return locator


def _locator(data_root: Path) -> _Locator:
    root = Path(data_root)
    shards = _ready_summary_shards(root)
    signature = _shard_signature(root, shards)
    cache_key = str(root)
    cached = _locator_cache.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    locator = _build_locator(shards)
    _locator_cache[cache_key] = (signature, locator)
    return locator


def _store_locator(data_root: Path, locator: _Locator) -> None:
    root = Path(data_root)
    _locator_cache[str(root)] = (_shard_signature(root), locator)


def _created_at_datetime(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


class FileSummaryStore:
    """摘要文件存储与同步底座。"""

    _MUT_FIELDS = (
        "summary_text",
        "translation_text",
        "model_provider",
        "model_name",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "cached",
        "is_generated_summary",
        "content_hash",
    )

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    @staticmethod
    def _to_domain(record: dict[str, Any]) -> SummaryRecord:
        return SummaryRecord(**record)

    async def seed(self, records: list[SummaryRecord]) -> None:
        for shard in paths.iter_summary_shards(self._root):
            async with shard_lock(shard):
                shard.unlink(missing_ok=True)

        grouped: dict[Path, list[dict[str, Any]]] = {}
        for record in records:
            shard = paths.summary_shard(self._root, record.created_at)
            grouped.setdefault(shard, []).append(record.model_dump(mode="json"))
        for shard, shard_records in grouped.items():
            async with shard_lock(shard):
                write_shard(shard, shard_records)
        _locator_cache.pop(str(self._root), None)

    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord:
        try:
            locator = _locator(self._root)
            by_tweet, by_summary = locator
            candidates = [
                location
                for location in by_tweet.get(record.tweet_id, [])
                if location.content_hash == record.content_hash
            ]
            existing_location = (
                max(candidates, key=lambda location: location.created_at) if candidates else None
            )
            if existing_location is not None:
                async with shard_lock(existing_location.shard):
                    shard_records = read_shard(existing_location.shard)
                    existing = next(
                        (
                            item
                            for item in shard_records
                            if item["summary_id"] == existing_location.summary_id
                        ),
                        None,
                    )
                    if existing is None:
                        raise RuntimeError(
                            f"定位表记录不存在: summary_id={existing_location.summary_id}"
                        )
                    incoming = record.model_dump(mode="json")
                    for field in self._MUT_FIELDS:
                        existing[field] = incoming[field]
                    existing["updated_at"] = _now_utc_iso()
                    write_shard(existing_location.shard, shard_records)

                _remove_location(locator, existing_location)
                _append_location(locator, existing_location.shard, existing)
                _store_locator(self._root, locator)
                return record.model_copy(update={"summary_id": existing["summary_id"]})

            raw = record.model_dump(mode="json")
            target = paths.summary_shard(self._root, record.created_at)
            same_id_location = by_summary.get(record.summary_id)
            if same_id_location is not None and same_id_location.shard != target:
                async with shard_lock(same_id_location.shard):
                    old_records = [
                        item
                        for item in read_shard(same_id_location.shard)
                        if item["summary_id"] != record.summary_id
                    ]
                    write_shard(same_id_location.shard, old_records)

            async with shard_lock(target):
                target_records = [
                    item
                    for item in read_shard(target)
                    if item["summary_id"] != record.summary_id
                ]
                target_records.append(raw)
                write_shard(target, target_records)

            if same_id_location is not None:
                _remove_location(locator, same_id_location)
            _append_location(locator, target, raw)
            _store_locator(self._root, locator)
            return record
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"保存摘要记录失败: {exc}") from exc

    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None:
        locations = _locator(self._root)[0].get(tweet_id, [])
        if len(locations) > 1:
            raise RepositoryError(f"查询推文摘要失败: 多条记录匹配 tweet_id={tweet_id}")
        if not locations:
            return None
        location = locations[0]
        record = next(
            (
                item
                for item in read_shard(location.shard)
                if item["summary_id"] == location.summary_id
            ),
            None,
        )
        return self._to_domain(record) if record is not None else None

    async def get_all_summaries(self) -> list[SummaryRecord]:
        """按分片名升序、片内原序枚举全部摘要记录。"""
        records: list[SummaryRecord] = []
        for shard in _ready_summary_shards(self._root):
            records.extend(self._to_domain(record) for record in read_shard(shard))
        return records

    async def summary_exists(self, summary_id: str) -> bool:
        return summary_id in _locator(self._root)[1]

    async def summary_id_of_tweet(self, tweet_id: str) -> str | None:
        locations = _locator(self._root)[0].get(tweet_id, [])
        if not locations:
            return None
        return max(locations, key=lambda location: location.created_at).summary_id

    async def upsert_summary(self, fields: dict[str, Any]) -> None:
        """按 summary_id 插入或全字段覆盖，跨月时先删旧片再写新片。"""
        locator = _locator(self._root)
        by_summary = locator[1]
        summary_id = str(fields["summary_id"])
        old_location = by_summary.get(summary_id)
        target = paths.summary_shard(
            self._root,
            _created_at_datetime(fields["created_at"]),
        )
        raw = {**fields, "updated_at": fields["created_at"]}

        if old_location is not None and old_location.shard != target:
            async with shard_lock(old_location.shard):
                old_records = [
                    item
                    for item in read_shard(old_location.shard)
                    if item["summary_id"] != summary_id
                ]
                write_shard(old_location.shard, old_records)

        async with shard_lock(target):
            target_records = [
                item for item in read_shard(target) if item["summary_id"] != summary_id
            ]
            target_records.append(raw)
            write_shard(target, target_records)

        if old_location is not None:
            _remove_location(locator, old_location)
        _append_location(locator, target, raw)
        _store_locator(self._root, locator)
