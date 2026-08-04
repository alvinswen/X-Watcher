"""CHG-054 stable grouping and query-construction contracts."""

import inspect

import pytest

from src.config import get_settings
from src.scraper.domain.scrape_group_state import ScrapeGroupState
from src.scraper.services.group_planner import (
    QUERY_RE,
    apply_membership_changes,
    assert_query_safe,
    build_query,
    plan_initial_groups,
)


def test_initial_pack_is_stable_20_20_20_8():
    usernames = [f"u{i:03d}" for i in range(68)]
    states = plan_initial_groups(list(reversed(usernames)))

    assert [len(state.usernames) for state in states] == [20, 20, 20, 8]
    assert [state.group_id for state in states] == ["g1", "g2", "g3", "g4"]
    assert [name for state in states for name in state.usernames] == sorted(usernames)
    assert all(len(build_query(state.usernames, "2084438126769127788")) < 450 for state in states)


def test_account_boundary_and_whitelist_reject_before_io():
    twenty = [f"u{i:02d}" for i in range(20)]
    query = build_query(twenty, "2084438126769127788")
    assert QUERY_RE.fullmatch(query)

    with pytest.raises(ValueError, match="21.*20"):
        build_query([*twenty, "u20"], "2084438126769127788")

    for suffix in (" include:replies", " filter:media", " lang:en"):
        with pytest.raises(ValueError, match="白名单"):
            assert_query_safe(twenty, query + suffix)


def _names_with_total_length(total: int) -> list[str]:
    names = [f"u{i:02d}" + "x" * 8 for i in range(19)]
    names.append("z" * (total - sum(map(len, names))))
    return names


def test_actual_query_length_boundary_includes_since_id():
    query_449 = build_query(_names_with_total_length(219), "2084438126769127788")
    assert len(query_449) == 449

    names_450 = _names_with_total_length(220)
    raw_450 = (
        f"({' OR '.join(f'from:{name}' for name in names_450)})"
        " include:nativeretweets since_id:2084438126769127788"
    )
    assert len(raw_450) == 450
    with pytest.raises(ValueError, match="450"):
        assert_query_safe(names_450, raw_450)


def test_membership_changes_append_without_reordering_or_watermark_reset():
    states = [
        ScrapeGroupState(
            group_id=f"g{i + 1}",
            usernames=[f"u{i * 20 + j:03d}" for j in range(size)],
            since_id=str(100 + i),
        )
        for i, size in enumerate((20, 20, 20, 8))
    ]
    before_membership = {
        name: state.group_id for state in states for name in state.usernames
    }
    before_watermarks = {state.group_id: state.since_id for state in states}

    changed = apply_membership_changes(states, [*before_membership, "a_new"])
    after_membership = {
        name: state.group_id for state in changed for name in state.usernames
    }
    assert all(after_membership[name] == group for name, group in before_membership.items())
    assert after_membership["a_new"] == "g4"
    assert {state.group_id: state.since_id for state in changed} == before_watermarks
    assert sum(a.usernames != b.usernames for a, b in zip(states, changed, strict=True)) == 1

    restored = apply_membership_changes(changed, list(before_membership))
    assert [state.model_dump() for state in restored] == [state.model_dump() for state in states]


def test_bridge_and_new_account_allowances_are_distinct_and_branch_local():
    from src.scraper.services.incremental_scrape_service import IncrementalScrapeService

    settings = get_settings()
    assert settings.scraper_incremental_bridge_tweets == 100
    assert settings.scraper_incremental_new_account_backfill_tweets == 200
    assert settings.scraper_incremental_bridge_tweets != settings.scraper_incremental_new_account_backfill_tweets
    bridge_source = inspect.getsource(IncrementalScrapeService._bridge_backfill)
    new_account_source = inspect.getsource(IncrementalScrapeService._backfill_new_account)
    assert "scraper_incremental_bridge_tweets" in bridge_source
    assert "scraper_incremental_new_account_backfill_tweets" not in bridge_source
    assert "scraper_incremental_new_account_backfill_tweets" in new_account_source
    assert "scraper_incremental_bridge_tweets" not in new_account_source
