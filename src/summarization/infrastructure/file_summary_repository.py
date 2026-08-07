"""文件版 SummaryStore：按摘要创建时间写入月度 JSONL 分片。"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
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

SUMMARY_BATCH_REFRESH_SIZE = 500

_batch_progress: contextvars.ContextVar[tuple[int, int] | None] = contextvars.ContextVar(
    "summary_batch_progress", default=None
)


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


@contextmanager
def summary_write_progress(index: int, total: int) -> Iterator[None]:
    """标注本轮进度(第 N 条 / 共 M 条),供撞车运行记录取用;不改任何写入语义。"""
    token = _batch_progress.set((index, total))
    try:
        yield
    finally:
        _batch_progress.reset(token)


def _discard_locator(data_root: Path) -> None:
    _locator_cache.pop(str(Path(data_root)), None)


def _take_locator(data_root: Path) -> _Locator:
    locator = _locator(data_root)
    _discard_locator(data_root)
    return locator


class _BatchSession:
    __slots__ = ("segment_size", "refreshes")

    def __init__(self, segment_size: int) -> None:
        self.segment_size = segment_size
        self.refreshes = 0


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
        self._batch: _Locator | None = None
        self._session: _BatchSession | None = None
        self._writes_in_segment = 0

    def _current_locator(self) -> _Locator:
        if self._batch is not None:
            return self._batch
        return _locator(self._root)

    def _after_write(self) -> None:
        if self._batch is None or self._session is None:
            _discard_locator(self._root)
            return
        self._writes_in_segment += 1
        if self._writes_in_segment >= self._session.segment_size:
            self._writes_in_segment = 0
            self._session.refreshes += 1
            self._batch = _take_locator(self._root)

    @asynccontextmanager
    async def batch_session(
        self, segment_size: int = SUMMARY_BATCH_REFRESH_SIZE
    ) -> AsyncIterator[_BatchSession]:
        session = _BatchSession(segment_size)
        self._session = session
        self._batch = _take_locator(self._root)
        self._writes_in_segment = 0
        try:
            yield session
        finally:
            self._batch = None
            self._session = None
            self._writes_in_segment = 0
            _discard_locator(self._root)

    @staticmethod
    def _to_domain(record: dict[str, Any]) -> SummaryRecord:
        return SummaryRecord(**record)

    @staticmethod
    def _log_collision(target: Path, tweet_id: str) -> None:
        progress = _batch_progress.get()
        logger.warning(
            "摘要撞车拦截: at=%s month=%s progress=%s tweet_id=%s 处置=已用本次内容覆盖既有那条",
            _now_utc_iso(),
            target.stem,
            f"{progress[0]}/{progress[1]}" if progress is not None else "-",
            tweet_id,
        )

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
        _discard_locator(self._root)

    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord:
        try:
            locator = self._current_locator()
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
                self._after_write()
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
                collision = next(
                    (
                        item
                        for item in target_records
                        if str(item.get("tweet_id")) == record.tweet_id
                        and str(item.get("content_hash")) == record.content_hash
                    ),
                    None,
                )
                if collision is not None:
                    for field in self._MUT_FIELDS:
                        collision[field] = raw[field]
                    collision["updated_at"] = _now_utc_iso()
                    write_shard(target, target_records)
                    _append_location(locator, target, collision)
                    self._log_collision(target, record.tweet_id)
                    self._after_write()
                    return record.model_copy(
                        update={"summary_id": str(collision["summary_id"])}
                    )
                target_records.append(raw)
                write_shard(target, target_records)

            if same_id_location is not None:
                _remove_location(locator, same_id_location)
            _append_location(locator, target, raw)
            self._after_write()
            return record
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"保存摘要记录失败: {exc}") from exc

    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None:
        locations = self._current_locator()[0].get(tweet_id, [])
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
        return summary_id in self._current_locator()[1]

    async def summary_id_of_tweet(self, tweet_id: str) -> str | None:
        locations = self._current_locator()[0].get(tweet_id, [])
        if not locations:
            return None
        return max(locations, key=lambda location: location.created_at).summary_id

    async def upsert_summary(self, fields: dict[str, Any]) -> None:
        """按 summary_id 插入或全字段覆盖，跨月时先删旧片再写新片。"""
        locator = self._current_locator()
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
        self._after_write()
