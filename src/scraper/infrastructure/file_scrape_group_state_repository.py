"""Atomic file repository for incremental scrape group state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.scraper.domain.scrape_group_state import GroupAlert, ScrapeGroupState
from src.storage import paths
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


class FileScrapeGroupStateStore:
    """Store all stable group states in one guarded JSON document."""

    def __init__(self, data_root: Path) -> None:
        self._path = paths.scrape_group_state_doc(Path(data_root))

    def _load(self) -> dict[str, Any]:
        doc = read_doc(self._path)
        if doc is None:
            return {"version": 1, "groups": {}}
        return doc

    @staticmethod
    def _to_domain(record: dict[str, Any]) -> ScrapeGroupState:
        return ScrapeGroupState(**record)

    @staticmethod
    def _sort_key(state: ScrapeGroupState) -> tuple[int, str]:
        suffix = state.group_id.removeprefix("g")
        return (int(suffix) if suffix.isdigit() else 10**9, state.group_id)

    @staticmethod
    def _with_monotonic_watermark(
        previous: ScrapeGroupState | None,
        incoming: ScrapeGroupState,
    ) -> ScrapeGroupState:
        state = incoming.model_copy(deep=True)
        if previous is not None and previous.bridge_done:
            state.bridge_done = True
        if previous is None or previous.since_id is None:
            return state
        rollback = state.since_id is None
        if state.since_id is not None:
            try:
                rollback = int(state.since_id) < int(previous.since_id)
            except ValueError:
                rollback = True
        if not rollback:
            return state

        state.since_id = previous.since_id
        existing_alerts = list(state.alerts)
        for alert in previous.alerts:
            if alert not in existing_alerts:
                existing_alerts.insert(0, alert)
        existing_alerts.append(
            GroupAlert(
                kind="watermark_rollback_blocked",
                group_id=state.group_id,
                detail={
                    "kept_since_id": previous.since_id,
                    "rejected_since_id": incoming.since_id,
                },
                advice="已阻止组水位回退；请核对并发写入方与进度档来源。",
                at=datetime.now(UTC).isoformat(),
            )
        )
        state.alerts = existing_alerts[-5:]
        return state

    async def load_all(self) -> list[ScrapeGroupState]:
        states = [self._to_domain(record) for record in self._load()["groups"].values()]
        return sorted(states, key=self._sort_key)

    async def upsert_group(self, state: ScrapeGroupState) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            old_record = doc["groups"].get(state.group_id)
            previous = self._to_domain(old_record) if old_record is not None else None
            safe = self._with_monotonic_watermark(previous, state)
            doc["groups"][safe.group_id] = safe.model_dump(mode="json")
            atomic_write_doc(self._path, doc)

    async def replace_all(self, states: list[ScrapeGroupState]) -> None:
        async with shard_lock(self._path):
            old_doc = self._load()
            records: dict[str, Any] = {}
            for state in states:
                old_record = old_doc["groups"].get(state.group_id)
                previous = self._to_domain(old_record) if old_record is not None else None
                safe = self._with_monotonic_watermark(previous, state)
                records[safe.group_id] = safe.model_dump(mode="json")
            atomic_write_doc(self._path, {"version": 1, "groups": records})

    async def mark_bridge_started(self, group_id: str) -> bool:
        """Atomically claim a group's one-time bridge operation."""
        async with shard_lock(self._path):
            doc = self._load()
            record = doc["groups"].get(group_id)
            if record is None:
                raise KeyError(f"抓取组不存在: {group_id}")
            state = self._to_domain(record)
            if state.bridge_done:
                return False
            state.bridge_done = True
            doc["groups"][group_id] = state.model_dump(mode="json")
            atomic_write_doc(self._path, doc)
            return True
