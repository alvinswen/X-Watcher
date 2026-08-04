"""CHG-054 group-state persistence and monotonicity contracts."""

import json

import pytest

from src.scraper.domain.scrape_group_state import (
    GroupAlert,
    ReconcileOutcome,
    RoundOutcome,
    ScrapeGroupState,
)
from src.scraper.infrastructure.file_scrape_group_state_repository import (
    FileScrapeGroupStateStore,
)


def _full_state(group_id: str = "g1", since_id: str | None = "200") -> ScrapeGroupState:
    return ScrapeGroupState(
        group_id=group_id,
        usernames=["alice", "bob"],
        since_id=since_id,
        bridge_done=True,
        resume_cursor="cursor-2",
        resume_since_id="100",
        resume_rounds=2,
        consecutive_clean_rounds=3,
        consecutive_stalled_rounds=1,
        backfilled_usernames=["bob"],
        last_path="dual",
        last_round_at="2026-08-04T05:00:00+00:00",
        last_round=RoundOutcome(fetched=4, new=3, duplicate_discarded=1, pages_fetched=1),
        last_reconcile=ReconcileOutcome(extra=1, extra_ids=["201"]),
        alerts=[GroupAlert(kind="example", group_id=group_id, advice="inspect")],
    )


@pytest.mark.asyncio
async def test_missing_file_upsert_and_round_trip_all_fields(tmp_path):
    repo = FileScrapeGroupStateStore(tmp_path)
    assert await repo.load_all() == []

    expected = _full_state()
    await repo.upsert_group(expected)
    actual = (await FileScrapeGroupStateStore(tmp_path).load_all())[0]
    assert actual == expected

    path = tmp_path / "scrape_state" / "groups.json"
    assert path.exists()
    assert json.loads(path.read_text())["version"] == 1
    assert len(ScrapeGroupState.model_fields) == 15


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_blocks_none_or_smaller_watermark(tmp_path):
    repo = FileScrapeGroupStateStore(tmp_path)
    original = _full_state(since_id="200")
    original.alerts = []
    await repo.upsert_group(original)
    await repo.upsert_group(original)
    assert len(await repo.load_all()) == 1

    await repo.upsert_group(original.model_copy(update={"since_id": None}))
    held = (await repo.load_all())[0]
    assert held.since_id == "200"
    assert held.alerts[-1].kind == "watermark_rollback_blocked"

    await repo.upsert_group(original.model_copy(update={"since_id": "199"}))
    assert (await repo.load_all())[0].since_id == "200"
    await repo.upsert_group(original.model_copy(update={"since_id": "201"}))
    assert (await repo.load_all())[0].since_id == "201"


@pytest.mark.asyncio
async def test_replace_all_enforces_watermark_for_each_group(tmp_path):
    repo = FileScrapeGroupStateStore(tmp_path)
    await repo.replace_all([_full_state("g1", "200"), _full_state("g2", "300")])

    await repo.replace_all([_full_state("g1", None), _full_state("g2", "299")])
    states = {state.group_id: state for state in await repo.load_all()}
    assert states["g1"].since_id == "200"
    assert states["g2"].since_id == "300"
    assert states["g1"].alerts[-1].kind == "watermark_rollback_blocked"
    assert states["g2"].alerts[-1].kind == "watermark_rollback_blocked"

    await repo.replace_all([_full_state("g1", "201"), _full_state("g2", "301")])
    assert [state.since_id for state in await repo.load_all()] == ["201", "301"]


@pytest.mark.asyncio
async def test_bridge_claim_is_atomic_and_at_most_once(tmp_path):
    repo = FileScrapeGroupStateStore(tmp_path)
    state = _full_state()
    state.bridge_done = False
    await repo.upsert_group(state)

    assert await repo.mark_bridge_started("g1") is True
    assert await repo.mark_bridge_started("g1") is False
    await repo.upsert_group(state)
    assert (await repo.load_all())[0].bridge_done is True
