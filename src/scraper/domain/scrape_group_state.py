"""Incremental scrape group state domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class RoundOutcome(BaseModel):
    """Observable result of one incremental group round."""

    fetched: int = 0
    new: int = 0
    duplicate_discarded: int = 0
    pages_fetched: int = 0
    complete: bool = True
    error_message: str | None = None


class ReconcileOutcome(BaseModel):
    """Directional comparison between legacy and incremental results."""

    missing: int = 0
    extra: int = 0
    missing_ids: list[str] = Field(default_factory=list)
    extra_ids: list[str] = Field(default_factory=list)


class GroupAlert(BaseModel):
    """Actionable alert emitted while maintaining a scrape group."""

    kind: str
    group_id: str
    detail: dict[str, Any] = Field(default_factory=dict)
    advice: str
    at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ScrapeGroupState(BaseModel):
    """Persistent state for one stable incremental scrape group."""

    group_id: str
    usernames: list[str]
    since_id: str | None = None
    bridge_done: bool = False
    resume_cursor: str | None = None
    resume_since_id: str | None = None
    resume_rounds: int = 0
    consecutive_clean_rounds: int = 0
    consecutive_stalled_rounds: int = 0
    backfilled_usernames: list[str] = Field(default_factory=list)
    last_path: str = "legacy"
    last_round_at: str | None = None
    last_round: RoundOutcome | None = None
    last_reconcile: ReconcileOutcome | None = None
    alerts: list[GroupAlert] = Field(default_factory=list)
