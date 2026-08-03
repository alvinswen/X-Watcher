"""信源候选挖掘编排。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.data_layer.repositories import SourceCandidateStore
from src.preference.infrastructure.follow_store import FollowStore
from src.source_candidates.models import CitationSignal, MiningSignal, SourceCandidate
from src.subjects.protocol import SubjectRepoProtocol


class MiningValidationError(ValueError):
    """挖掘参数不合法。"""


class MiningNotFoundError(LookupError):
    """挖掘依赖的业务对象不存在。"""


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MiningService:
    def __init__(
        self,
        store: SourceCandidateStore,
        follow_store: FollowStore,
        subject_store: SubjectRepoProtocol,
    ) -> None:
        self._store = store
        self._follow_store = follow_store
        self._subject_store = subject_store

    async def mine(
        self,
        *,
        subject_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        min_citations: int = 3,
        min_sources: int = 2,
        top_n: int = 20,
    ) -> dict[str, Any]:
        if min_citations < 1:
            raise MiningValidationError("min_citations 必须大于等于 1")
        if min_sources < 1:
            raise MiningValidationError("min_sources 必须大于等于 1")
        if not 1 <= top_n <= 100:
            raise MiningValidationError("top_n 必须在 1 到 100 之间")
        since = _aware_utc(since)
        until = _aware_utc(until)
        if since is not None and until is not None and since > until:
            raise MiningValidationError("since 不能晚于 until")

        tweet_id_filter: set[str] | None = None
        if subject_id is not None:
            if await self._subject_store.get_subject(subject_id) is None:
                raise MiningNotFoundError("议题不存在")
            matches = await self._subject_store.list_matches(
                subject_id,
                since=since,
                until=until,
            )
            tweet_id_filter = {match.tweet_id for match in matches}

        follows = await self._follow_store.get_all_follows(include_inactive=True)
        suppressed_library = {follow.username.lower() for follow in follows}
        index_entries = await self._store.all_index_entries()
        suppressed_terminal = {
            str(entry["username"]).lower()
            for entry in index_entries.values()
            if entry.get("status") in {"approved", "rejected"}
        }
        merge_by_username = {
            str(entry["username"]).lower(): candidate_id
            for candidate_id, entry in index_entries.items()
            if entry.get("status") in {"discovered", "assessed"}
        }

        scan = await self._store.scan_citation_signals(
            tweet_id_filter,
            since,
            until,
        )
        raw_candidates: dict[str, dict[str, Any]] = scan["candidates"]
        now = datetime.now(UTC)
        merged_refreshed: list[str] = []
        eligible: list[tuple[int, int, str, str, MiningSignal]] = []
        suppressed_in_library = 0
        suppressed_pool_terminal = 0

        for username_lower, raw in raw_candidates.items():
            raw_citations: dict[str, set[str]] = raw["citations"]
            citations = {
                source: CitationSignal(
                    count=len(tweet_ids),
                    citing_tweet_ids=sorted(tweet_ids),
                )
                for source, tweet_ids in raw_citations.items()
            }
            all_tweet_ids = sorted(
                {tweet_id for item in citations.values() for tweet_id in item.citing_tweet_ids}
            )
            signal = MiningSignal(
                citations=citations,
                citation_total=sum(item.count for item in citations.values()),
                source_diversity=len(citations),
                sample_citation_tweet_ids=all_tweet_ids[-10:],
                subject_tags=[subject_id] if subject_id is not None else [],
                first_discovered_at=now,
                last_mined_at=now,
            )
            if username_lower in suppressed_library:
                suppressed_in_library += 1
                continue
            if username_lower in suppressed_terminal:
                suppressed_pool_terminal += 1
                continue
            existing_id = merge_by_username.get(username_lower)
            if existing_id is not None:
                await self._store.merge_mining_signal(existing_id, signal, subject_id)
                merged_refreshed.append(existing_id)
                continue
            if (
                signal.citation_total >= min_citations
                and signal.source_diversity >= min_sources
            ):
                eligible.append(
                    (
                        signal.citation_total,
                        signal.source_diversity,
                        username_lower,
                        str(raw["username_display"]),
                        signal,
                    )
                )

        eligible.sort(key=lambda item: (-item[0], -item[1], item[2]))
        admitted: list[dict[str, Any]] = []
        for total, diversity, candidate_id, display_name, signal in eligible[:top_n]:
            candidate = SourceCandidate(
                candidate_id=candidate_id,
                username=display_name,
                mining=signal,
            )
            await self._store.upsert_candidate(candidate)
            admitted.append(
                {
                    "candidate_id": candidate_id,
                    "username": display_name,
                    "citation_total": total,
                    "source_diversity": diversity,
                    "subject_tags": signal.subject_tags,
                }
            )

        return {
            "mined": admitted,
            "merged_refreshed": merged_refreshed,
            "stats": {
                "scanned_tweets": int(scan["scanned_tweets"]),
                "signal_candidates": len(raw_candidates),
                "above_threshold": len(eligible),
                "suppressed_in_library": suppressed_in_library,
                "suppressed_pool_terminal": suppressed_pool_terminal,
                "merged_nonterminal": len(merged_refreshed),
                "admitted": len(admitted),
            },
        }
