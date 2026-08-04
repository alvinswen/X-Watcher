"""Incremental grouped scraping orchestration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, cast

from returns.result import Failure, Success

from src.config import get_settings
from src.scraper.client import TwitterClient
from src.scraper.domain.models import Tweet
from src.scraper.domain.scrape_group_state import (
    GroupAlert,
    ReconcileOutcome,
    RoundOutcome,
    ScrapeGroupState,
)
from src.scraper.parser import TweetParser
from src.scraper.services.group_planner import (
    apply_membership_changes,
    build_query,
    plan_initial_groups,
)
from src.scraper.validator import TweetValidator


class IncrementalScrapeService:
    """Run bridge, grouped incremental fetch, and directional reconciliation."""

    def __init__(
        self,
        client: TwitterClient | None = None,
        parser: TweetParser | None = None,
        validator: TweetValidator | None = None,
        state_repo: Any | None = None,
        tweet_repo: Any | None = None,
    ) -> None:
        from src.data_layer.provider import (
            get_scrape_group_state_repo,
            get_tweet_repo,
        )

        self._owns_client = client is None
        self._client = client or TwitterClient()
        self._parser = parser or TweetParser()
        self._validator = validator or TweetValidator()
        self._state_repo = state_repo or get_scrape_group_state_repo()
        self._tweet_repo = tweet_repo or get_tweet_repo()
        self._group_tweets: dict[str, list[Tweet]] = {}
        self._legacy_ids: dict[str, set[str]] = {}
        self._reconcile_since_ids: dict[str, str | None] = {}
        self._query_chars: dict[str, int] = {}
        self._group_accounts: dict[str, int] = {}

    @staticmethod
    def _append_alert(state: ScrapeGroupState, alert: GroupAlert) -> None:
        state.alerts = [*state.alerts, alert][-5:]

    def _clean_tweets(self, raw_data: dict[str, Any]) -> list[Tweet]:
        parsed = self._parser.parse_tweet_response(raw_data)
        cleaned: list[Tweet] = []
        for validation in self._validator.validate_and_clean_batch(parsed):
            match validation:
                case Success(tweet):
                    cleaned.append(tweet)
                case Failure(_):
                    pass
        return cleaned

    @staticmethod
    def _effective_path(group_id: str) -> str:
        settings = get_settings()
        if not settings.scraper_incremental_enabled:
            return "legacy"
        cutover = {
            item.strip()
            for item in settings.scraper_incremental_cutover_groups.split(",")
            if item.strip()
        }
        return "cutover" if group_id in cutover else "dual"

    async def run_round(self, usernames: list[str]) -> dict[str, Any]:
        """Run one independently bounded round for every stable group."""
        states = await self._state_repo.load_all()
        initial = not states
        previous_members = {name for state in states for name in state.usernames}
        if initial:
            states = plan_initial_groups(usernames)
        else:
            states = apply_membership_changes(states, usernames)
        clean_before = {
            state.group_id: state.consecutive_clean_rounds for state in states
        }
        await self._state_repo.replace_all(states)

        new_usernames = set(usernames) - previous_members if not initial else set()
        for state in states:
            if not state.bridge_done:
                await self._bridge_backfill(state)
                await self._state_repo.upsert_group(state)
            for username in state.usernames:
                if username in new_usernames and username not in state.backfilled_usernames:
                    await self._backfill_new_account(state, username)
                    await self._state_repo.upsert_group(state)

        configured_sentinels = [
            item.strip()
            for item in get_settings().scraper_incremental_sentinels.split(",")
            if item.strip()
        ]
        missing_sentinels = sorted(set(configured_sentinels) - set(usernames))
        if missing_sentinels and states:
            self._append_alert(
                states[0],
                GroupAlert(
                    kind="sentinel_misconfigured",
                    group_id=states[0].group_id,
                    detail={"missing_sentinels": missing_sentinels},
                    advice="请把缺失哨兵恢复到活跃名单，或同步调整哨兵配置。",
                ),
            )

        outcomes: dict[str, RoundOutcome] = {}
        for state in states:
            if not state.usernames:
                await self._state_repo.upsert_group(state)
                continue
            state.last_path = self._effective_path(state.group_id)
            was_resuming = state.resume_cursor is not None
            self._reconcile_since_ids[state.group_id] = state.since_id

            if state.last_path == "dual":
                self._legacy_ids[state.group_id] = await self._run_legacy_group(state)

            outcome = await self._run_group(state)
            outcomes[state.group_id] = outcome
            new_ids = {tweet.tweet_id for tweet in self._group_tweets[state.group_id]}
            if (
                state.last_path == "dual"
                and not was_resuming
                and state.resume_cursor is None
            ):
                await self._reconcile(state, new_ids)
            await self._state_repo.upsert_group(state)

        suspected = self._sentinel_check(self._group_tweets)
        if suspected is not None and states:
            for state in states:
                state.consecutive_clean_rounds = clean_before[state.group_id]
            self._append_alert(states[0], suspected)

        for state in states:
            await self._state_repo.upsert_group(state)

        return {
            "total_groups": len(outcomes),
            "successful_groups": sum(outcome.complete for outcome in outcomes.values()),
            "fetched": sum(outcome.fetched for outcome in outcomes.values()),
            "new": sum(outcome.new for outcome in outcomes.values()),
            "duplicate_discarded": sum(
                outcome.duplicate_discarded for outcome in outcomes.values()
            ),
            "groups": {
                group_id: outcome.model_dump(mode="json")
                for group_id, outcome in outcomes.items()
            },
        }

    async def _run_legacy_group(self, state: ScrapeGroupState) -> set[str]:
        """Fetch the legacy comparison side without changing its endpoint semantics."""
        ids: set[str] = set()
        for username in state.usernames:
            result = await self._client.fetch_user_tweets(username)
            if isinstance(result, Failure):
                continue
            tweets = self._clean_tweets(result.unwrap())
            ids.update(tweet.tweet_id for tweet in tweets)
            if tweets:
                await self._tweet_repo.save_tweets(
                    tweets,
                    early_stop_threshold=get_settings().scraper_early_stop_threshold,
                )
        return ids

    async def _run_group(self, state: ScrapeGroupState) -> RoundOutcome:
        """Fetch and persist one group with an independent per-round page cap."""
        settings = get_settings()
        resuming = state.resume_cursor is not None
        since_used = state.resume_since_id if resuming else state.since_id
        cursor = state.resume_cursor if resuming else None
        query = build_query(state.usernames, since_used)
        self._query_chars[state.group_id] = len(query)
        self._group_accounts[state.group_id] = len(state.usernames)
        collected: list[Tweet] = []
        pages_fetched = 0
        complete = True
        hit_page_cap = False
        error_message: str | None = None
        resume_invalid = False

        for page_index in range(settings.scraper_incremental_max_pages_per_round):
            result = await self._client.search_tweets_incremental(
                query,
                cursor=cursor,
            )
            if isinstance(result, Failure):
                complete = False
                error_message = result.failure().message
                resume_invalid = resuming and page_index == 0
                break

            page = result.unwrap()
            pages_fetched += 1
            tweets = self._clean_tweets(page)
            if resuming and page_index == 0 and not tweets:
                complete = False
                error_message = "续翻游标失效：首个续翻页为空"
                resume_invalid = True
                break
            collected.extend(tweets)
            if not tweets:
                break
            next_cursor = page.get("next_cursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)
            if page_index < settings.scraper_incremental_max_pages_per_round - 1:
                await asyncio.sleep(1.0)
        else:
            hit_page_cap = True

        saved = await self._tweet_repo.save_tweets(
            collected,
            early_stop_threshold=0,
        )
        outcome = RoundOutcome(
            fetched=len(collected),
            new=saved.success_count,
            duplicate_discarded=saved.skipped_count,
            pages_fetched=pages_fetched,
            complete=complete and not hit_page_cap,
            error_message=error_message,
        )
        state.last_round = outcome
        state.last_round_at = datetime.now(UTC).isoformat()
        self._group_tweets[state.group_id] = collected

        if resume_invalid:
            state.resume_cursor = None
            state.resume_since_id = None
            state.resume_rounds = 0
        else:
            settlement_tweets = collected
            if resuming and complete and not hit_page_cap:
                settlement_tweets = await self._resume_watermark_tweets(
                    state,
                    collected,
                    since_used,
                )
            self._settle_round(
                state,
                settlement_tweets,
                complete,
                hit_page_cap,
                cursor,
                since_used,
                resuming,
            )
        return outcome

    async def _resume_watermark_tweets(
        self,
        state: ScrapeGroupState,
        collected: list[Tweet],
        since_used: str | None,
    ) -> list[Tweet]:
        """Recover the newest item from all persisted pages in a resumed sequence."""
        reader = getattr(self._tweet_repo, "get_tweets_by_author", None)
        if reader is None:
            return collected
        recovered = list(collected)
        for username in state.usernames:
            for tweet in await reader(username, limit=1_000_000):
                if since_used is None or int(tweet.tweet_id) > int(since_used):
                    recovered.append(tweet)
        return recovered

    def _advance_or_hold(
        self,
        state: ScrapeGroupState,
        collected: list[Tweet],
        complete: bool,
    ) -> None:
        """Advance only after complete IO and an overlap-eligible tweet."""
        settings = get_settings()
        if not complete:
            state.consecutive_stalled_rounds += 1
            if (
                state.consecutive_stalled_rounds
                >= settings.scraper_incremental_stalled_rounds_alert
            ):
                self._append_alert(
                    state,
                    GroupAlert(
                        kind="progress_stalled",
                        group_id=state.group_id,
                        detail={
                            "stalled_rounds": state.consecutive_stalled_rounds
                        },
                        advice="该组连续抓取失败，请检查上游网络与查询响应后重试。",
                    ),
                )
            return

        cutoff = datetime.now(UTC) - timedelta(
            minutes=settings.scraper_incremental_overlap_minutes
        )
        eligible = [
            tweet
            for tweet in collected
            if (
                tweet.created_at.replace(tzinfo=UTC)
                if tweet.created_at.tzinfo is None
                else tweet.created_at.astimezone(UTC)
            )
            < cutoff
        ]
        if not eligible:
            return
        candidate = max((tweet.tweet_id for tweet in eligible), key=int)
        if state.since_id is None or int(candidate) > int(state.since_id):
            state.since_id = candidate
            state.consecutive_stalled_rounds = 0

    def _settle_round(
        self,
        state: ScrapeGroupState,
        collected: list[Tweet],
        complete: bool,
        hit_page_cap: bool,
        cursor: str | None,
        since_used: str | None,
        resuming: bool,
    ) -> None:
        """Persist a continuation, discard a failed one, or advance normally."""
        del resuming
        settings = get_settings()
        if hit_page_cap:
            state.resume_cursor = cursor
            state.resume_since_id = since_used
            state.resume_rounds += 1
            if state.resume_rounds >= settings.scraper_incremental_resume_rounds_alert:
                self._append_alert(
                    state,
                    GroupAlert(
                        kind="backlog_drain_slow",
                        group_id=state.group_id,
                        detail={"resume_rounds": state.resume_rounds},
                        advice="积压消化异常缓慢；请核对每组每轮页数闸与触发频率。",
                    ),
                )
            return
        state.resume_cursor = None
        state.resume_since_id = None
        state.resume_rounds = 0
        self._advance_or_hold(state, collected, complete)

    async def _reconcile(
        self,
        state: ScrapeGroupState,
        new_ids: set[str],
    ) -> ReconcileOutcome:
        """Compare directionally after windowing the legacy result."""
        old_ids = self._legacy_ids.get(state.group_id, set())
        since_id = self._reconcile_since_ids.get(state.group_id, state.since_id)
        if since_id is not None:
            old_ids = {tweet_id for tweet_id in old_ids if int(tweet_id) > int(since_id)}
        missing_ids = sorted(old_ids - new_ids, key=int)
        extra_ids = sorted(new_ids - old_ids, key=int)
        outcome = ReconcileOutcome(
            missing=len(missing_ids),
            extra=len(extra_ids),
            missing_ids=missing_ids,
            extra_ids=extra_ids,
        )
        state.last_reconcile = outcome
        if missing_ids:
            state.consecutive_clean_rounds = 0
        else:
            state.consecutive_clean_rounds += 1
        return outcome

    def _sentinel_check(
        self,
        round_results: dict[str, list[Tweet]],
    ) -> GroupAlert | None:
        """Emit one actionable alert for an all-zero incremental round."""
        settings = get_settings()
        tweets = [tweet for group in round_results.values() for tweet in group]
        sentinels = [
            item.strip()
            for item in settings.scraper_incremental_sentinels.split(",")
            if item.strip()
        ]
        hits = {
            sentinel: sum(
                tweet.author_username.lower() == sentinel.lower() for tweet in tweets
            )
            for sentinel in sentinels
        }
        if tweets or any(hits.values()) or not round_results:
            return None
        group_id = next(iter(round_results))
        return GroupAlert(
            kind="suspected_query_failure",
            group_id=group_id,
            detail={
                "query_chars": self._query_chars.get(group_id, 0),
                "accounts": self._group_accounts.get(group_id, 0),
                "sentinels": hits,
                "total_fetched": 0,
            },
            advice="整轮与全部哨兵均为零，疑似查询静默失效；建议拆分并复核该组查询。",
        )

    async def _bridge_backfill(self, state: ScrapeGroupState) -> None:
        """Run the one-time per-account bridge through the legacy paginator."""
        if state.bridge_done:
            return
        claimed = await cast(Any, self._state_repo).mark_bridge_started(state.group_id)
        state.bridge_done = True
        if not claimed:
            return

        settings = get_settings()
        target = settings.scraper_incremental_bridge_tweets
        collected: list[Tweet] = []
        for username in state.usernames:
            remaining = target
            async for page in self._client.fetch_user_tweets_paginated(
                username,
                max_pages=ceil(target / 20) if target else 0,
            ):
                tweets = self._clean_tweets(page)[:remaining]
                remaining -= len(tweets)
                if tweets:
                    await self._tweet_repo.save_tweets(
                        tweets,
                        early_stop_threshold=0,
                    )
                    collected.extend(tweets)
                if remaining <= 0:
                    break
        self._advance_or_hold(state, collected, complete=True)

    async def _backfill_new_account(
        self,
        state: ScrapeGroupState,
        username: str,
    ) -> None:
        """Fetch the independent new-account history allowance once."""
        target = get_settings().scraper_incremental_new_account_backfill_tweets
        remaining = target
        async for page in self._client.fetch_user_tweets_paginated(
            username,
            max_pages=ceil(target / 20) if target else 0,
        ):
            tweets = self._clean_tweets(page)[:remaining]
            remaining -= len(tweets)
            if tweets:
                await self._tweet_repo.save_tweets(
                    tweets,
                    early_stop_threshold=0,
                )
            if remaining <= 0:
                break
        state.backfilled_usernames = [*state.backfilled_usernames, username]

    async def close(self) -> None:
        """Close the HTTP client only when this service created it."""
        if self._owns_client:
            await self._client.close()
