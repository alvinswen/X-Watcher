"""Pure stable grouping and incremental-query construction."""

from __future__ import annotations

import re

from src.config import get_settings
from src.scraper.domain.scrape_group_state import ScrapeGroupState

QUERY_RE = re.compile(
    r"^\(from:[A-Za-z0-9_]{1,15}(?: OR from:[A-Za-z0-9_]{1,15})*\)"
    r" include:nativeretweets"
    r"(?: since_id:\d+)?$"
)
_CAPACITY_SINCE_ID = "9999999999999999999"


def assert_query_safe(usernames: list[str], query: str) -> None:
    """Fail before IO unless the complete outgoing query is safe."""
    settings = get_settings()
    if not usernames:
        raise ValueError("增量查询账号列表不能为空")
    if len(set(usernames)) != len(usernames):
        raise ValueError("增量查询账号列表不得包含重复账号")
    if len(usernames) > settings.scraper_incremental_max_accounts_per_group:
        raise ValueError(
            "增量查询账号数 "
            f"{len(usernames)} 超过上限 "
            f"{settings.scraper_incremental_max_accounts_per_group}"
        )
    if len(query) >= settings.scraper_incremental_max_query_chars:
        raise ValueError(
            f"增量查询串长度 {len(query)} 达到或超过上限 "
            f"{settings.scraper_incremental_max_query_chars}"
        )
    if QUERY_RE.fullmatch(query) is None:
        raise ValueError("增量查询串包含白名单外结构或操作符")


def build_query(usernames: list[str], since_id: str | None) -> str:
    """Build and validate the exact query sent to advanced_search."""
    query = f"({' OR '.join(f'from:{name}' for name in usernames)}) include:nativeretweets"
    if since_id is not None:
        query += f" since_id:{since_id}"
    assert_query_safe(usernames, query)
    return query


def _fits(usernames: list[str], since_id: str | None) -> bool:
    try:
        build_query(usernames, since_id or _CAPACITY_SINCE_ID)
    except ValueError:
        return False
    return True


def plan_initial_groups(usernames: list[str]) -> list[ScrapeGroupState]:
    """Sort once and pack accounts without creating a future query overflow."""
    unique = sorted(set(usernames))
    states: list[ScrapeGroupState] = []
    current: list[str] = []
    for username in unique:
        candidate = [*current, username]
        if current and not _fits(candidate, None):
            states.append(
                ScrapeGroupState(group_id=f"g{len(states) + 1}", usernames=current)
            )
            current = [username]
            if not _fits(current, None):
                build_query(current, _CAPACITY_SINCE_ID)
        else:
            current = candidate
    if current:
        states.append(
            ScrapeGroupState(group_id=f"g{len(states) + 1}", usernames=current)
        )
    return states


def apply_membership_changes(
    states: list[ScrapeGroupState],
    active_usernames: list[str],
) -> list[ScrapeGroupState]:
    """Remove inactive members and append new members without moving old ones."""
    active = set(active_usernames)
    result = [state.model_copy(deep=True) for state in states]
    for state in result:
        state.usernames = [name for name in state.usernames if name in active]
        state.backfilled_usernames = [
            name for name in state.backfilled_usernames if name in active
        ]

    assigned = {name for state in result for name in state.usernames}
    additions = sorted(active - assigned)
    for username in additions:
        if result and _fits(
            [*result[-1].usernames, username], result[-1].since_id
        ):
            result[-1].usernames.append(username)
            continue
        result.append(
            ScrapeGroupState(group_id=f"g{len(result) + 1}", usernames=[username])
        )
    return result
