"""信源候选域的文件仓储实现。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.source_candidates.models import (
    CandidateStatus,
    CitationSignal,
    MiningSignal,
    SourceCandidate,
)
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.storage.jsonl_store import read_shard
from src.storage.paths import (
    iter_canonical_shards,
    iter_source_candidate_docs,
    source_candidate_doc,
    source_candidate_index,
)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class FileSourceCandidateStore:
    """doc 是事实源、index 是派生索引的候选仓储。"""

    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)
        self._index_path = source_candidate_index(self._data_root)

    @staticmethod
    def _index_entry(candidate: SourceCandidate) -> dict[str, Any]:
        return {
            "username": candidate.username,
            "platform_user_id": candidate.platform_user_id,
            "status": candidate.status.value,
            "citation_total": candidate.mining.citation_total,
            "source_diversity": candidate.mining.source_diversity,
            "subject_tags": candidate.mining.subject_tags,
            "first_discovered_at": candidate.mining.first_discovered_at.isoformat(),
            "last_mined_at": candidate.mining.last_mined_at.isoformat(),
            "sample_fetched_at": (
                candidate.sample.fetched_at.isoformat() if candidate.sample else None
            ),
            "assessed_at": (
                candidate.assessment.assessed_at.isoformat()
                if candidate.assessment
                else None
            ),
            "decided_at": (
                candidate.decision.decided_at.isoformat() if candidate.decision else None
            ),
        }

    def _read_candidate(self, candidate_id: str) -> SourceCandidate | None:
        doc = read_doc(source_candidate_doc(self._data_root, candidate_id.lower()))
        return SourceCandidate.model_validate(doc) if doc is not None else None

    def _read_index(self) -> dict[str, dict[str, Any]] | None:
        try:
            doc = read_doc(self._index_path)
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or not isinstance(doc.get("candidates"), dict):
            return None
        return dict(doc["candidates"])

    def _write_candidate_and_index(
        self,
        candidate: SourceCandidate,
        entries: dict[str, dict[str, Any]],
    ) -> None:
        atomic_write_doc(
            source_candidate_doc(self._data_root, candidate.candidate_id),
            candidate.model_dump(mode="json"),
        )
        entries[candidate.candidate_id] = self._index_entry(candidate)
        atomic_write_doc(self._index_path, {"candidates": entries})

    def _entries_from_docs(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for path in iter_source_candidate_docs(self._data_root):
            doc = read_doc(path)
            if doc is None:
                continue
            candidate = SourceCandidate.model_validate(doc)
            entries[candidate.candidate_id] = self._index_entry(candidate)
        return entries

    async def seed(self, candidates: list[SourceCandidate]) -> None:
        async with shard_lock(self._index_path):
            entries: dict[str, dict[str, Any]] = {}
            for candidate in candidates:
                self._write_candidate_and_index(candidate, entries)

    async def get_candidate(self, candidate_id: str) -> SourceCandidate | None:
        return self._read_candidate(candidate_id)

    async def list_candidates(
        self,
        status: CandidateStatus | None = None,
        subject_id: str | None = None,
    ) -> list[SourceCandidate]:
        entries = self._read_index()
        if entries is None:
            await self.rebuild_index()
            entries = self._read_index() or {}
        candidates: list[SourceCandidate] = []
        for candidate_id, entry in entries.items():
            if status is not None and entry.get("status") != status.value:
                continue
            tags = entry.get("subject_tags", [])
            if subject_id is not None and subject_id not in tags:
                continue
            candidate = self._read_candidate(candidate_id)
            if candidate is not None:
                candidates.append(candidate)
        return sorted(
            candidates,
            key=lambda item: item.mining.first_discovered_at,
            reverse=True,
        )

    async def upsert_candidate(self, candidate: SourceCandidate) -> None:
        async with shard_lock(self._index_path):
            entries = self._read_index()
            if entries is None:
                entries = self._entries_from_docs()
            self._write_candidate_and_index(candidate, entries)

    async def get_candidate_by_platform_user_id(
        self, platform_user_id: str
    ) -> SourceCandidate | None:
        entries = self._read_index()
        if entries is None:
            await self.rebuild_index()
            entries = self._read_index() or {}
        for candidate_id, entry in entries.items():
            if entry.get("platform_user_id") == platform_user_id:
                return self._read_candidate(candidate_id)
        return None

    async def all_index_entries(self) -> dict[str, dict[str, Any]]:
        entries = self._read_index()
        if entries is None:
            await self.rebuild_index()
            entries = self._read_index() or {}
        return entries

    async def scan_citation_signals(
        self,
        tweet_id_filter: set[str] | None,
        since: datetime | None,
        until: datetime | None,
    ) -> dict[str, Any]:
        candidates: dict[str, dict[str, Any]] = {}
        scanned_tweets = 0
        for shard in iter_canonical_shards(self._data_root):
            for row in read_shard(shard):
                tweet_id = str(row.get("tweet_id", ""))
                if tweet_id_filter is not None and tweet_id not in tweet_id_filter:
                    continue
                created_at = _parse_time(row.get("created_at"))
                if since is not None and (created_at is None or created_at < since):
                    continue
                if until is not None and (created_at is None or created_at > until):
                    continue
                scanned_tweets += 1
                if row.get("reference_type") not in {"retweeted", "quoted"}:
                    continue
                source = str(row.get("author_username", "")).strip()
                target = str(row.get("referenced_tweet_author_username", "")).strip()
                if not _USERNAME_RE.fullmatch(source) or not _USERNAME_RE.fullmatch(target):
                    continue
                source_lower = source.lower()
                target_lower = target.lower()
                if source_lower == target_lower:
                    continue
                bucket = candidates.setdefault(
                    target_lower,
                    {"username_display": target, "citations": {}},
                )
                bucket["username_display"] = target
                source_ids = bucket["citations"].setdefault(source_lower, set())
                source_ids.add(tweet_id)
        return {"scanned_tweets": scanned_tweets, "candidates": candidates}

    async def rebuild_index(self) -> None:
        async with shard_lock(self._index_path):
            atomic_write_doc(self._index_path, {"candidates": self._entries_from_docs()})

    async def merge_mining_signal(
        self,
        candidate_id: str,
        signal: MiningSignal,
        subject_id: str | None,
    ) -> SourceCandidate:
        async with shard_lock(self._index_path):
            candidate = self._read_candidate(candidate_id)
            if candidate is None:
                raise ValueError(f"候选不存在: {candidate_id}")
            if candidate.status.is_terminal:
                return candidate
            for source, incoming in signal.citations.items():
                existing = candidate.mining.citations.setdefault(source, CitationSignal())
                merged_ids = set(existing.citing_tweet_ids) | set(incoming.citing_tweet_ids)
                existing.citing_tweet_ids = sorted(merged_ids)
                existing.count = len(merged_ids)
            candidate.mining.citation_total = sum(
                item.count for item in candidate.mining.citations.values()
            )
            candidate.mining.source_diversity = len(candidate.mining.citations)
            all_ids = {
                tweet_id
                for item in candidate.mining.citations.values()
                for tweet_id in item.citing_tweet_ids
            }
            candidate.mining.sample_citation_tweet_ids = sorted(all_ids)[-10:]
            candidate.mining.last_mined_at = signal.last_mined_at
            if subject_id is not None:
                candidate.mining.subject_tags = sorted(
                    set(candidate.mining.subject_tags) | {subject_id}
                )
            entries = self._read_index()
            if entries is None:
                entries = self._entries_from_docs()
            self._write_candidate_and_index(candidate, entries)
            return candidate
