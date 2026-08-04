"""CHG-054 incremental orchestration state-machine contracts."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from returns.result import Failure, Success

from src.config import clear_settings_cache
from src.scraper.client import TwitterClientError
from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.domain.scrape_group_state import ScrapeGroupState
from src.scraper.infrastructure.file_scrape_group_state_repository import (
    FileScrapeGroupStateStore,
)
from src.scraper.services.incremental_scrape_service import IncrementalScrapeService


class PassthroughParser:
    def parse_tweet_response(self, raw_data):
        return raw_data.get("tweets", [])


class PassthroughValidator:
    def validate_and_clean_batch(self, tweets):
        return [Success(tweet) for tweet in tweets]


class MemoryTweetRepo:
    def __init__(self):
        self.tweets = {}
        self.thresholds = []

    async def save_tweets(self, tweets, early_stop_threshold=5):
        self.thresholds.append(early_stop_threshold)
        saved = []
        skipped = 0
        for tweet in tweets:
            if tweet.tweet_id in self.tweets:
                skipped += 1
            else:
                self.tweets[tweet.tweet_id] = tweet
                saved.append(tweet.tweet_id)
        return SaveResult(
            success_count=len(saved),
            skipped_count=skipped,
            error_count=0,
            saved_tweet_ids=saved,
        )

    async def get_tweets_by_author(self, author_username, limit=100):
        matches = [
            tweet
            for tweet in self.tweets.values()
            if tweet.author_username == author_username
        ]
        return sorted(matches, key=lambda tweet: int(tweet.tweet_id), reverse=True)[:limit]


class FakeClient:
    def __init__(self, advanced_results=(), legacy=None, history=None):
        self.advanced_results = list(advanced_results)
        self.legacy = legacy or Success({"tweets": []})
        self.history = history or {}
        self.incremental_calls = []
        self.legacy_calls = []
        self.history_calls = []

    async def search_tweets_incremental(self, query, *, cursor=None):
        self.incremental_calls.append({"query": query, "cursor": cursor})
        return self.advanced_results.pop(0)

    async def fetch_user_tweets(self, username, *, cursor=None):
        self.legacy_calls.append({"username": username, "cursor": cursor})
        return self.legacy

    async def fetch_user_tweets_paginated(self, username, *, max_pages=10, page_delay=1.0):
        del page_delay
        self.history_calls.append({"username": username, "max_pages": max_pages})
        for page in self.history.get(username, [])[:max_pages]:
            yield page

    async def close(self):
        return None


def _tweet(tweet_id, author="alice", *, minutes_old=60):
    return Tweet(
        tweet_id=str(tweet_id),
        text=f"tweet-{tweet_id}",
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_old),
        author_username=author,
    )


def _page(*tweets, cursor=None):
    return {"tweets": list(tweets), "next_cursor": cursor}


def _service(client, repo=None, state_repo=None):
    return IncrementalScrapeService(
        client=client,
        parser=PassthroughParser(),
        validator=PassthroughValidator(),
        state_repo=state_repo or Mock(),
        tweet_repo=repo or MemoryTweetRepo(),
    )


def _set_page_cap(monkeypatch, cap):
    monkeypatch.setenv("SCRAPER_INCREMENTAL_MAX_PAGES_PER_ROUND", str(cap))
    clear_settings_cache()


@pytest.mark.asyncio
async def test_second_page_failure_saves_partial_and_holds_watermark(monkeypatch):
    _set_page_cap(monkeypatch, 5)
    monkeypatch.setattr("src.scraper.services.incremental_scrape_service.asyncio.sleep", AsyncMock())
    repo = MemoryTweetRepo()
    client = FakeClient(
        [
            Success(_page(_tweet(201), cursor="c1")),
            Failure(TwitterClientError("page two failed")),
        ]
    )
    state = ScrapeGroupState(group_id="g1", usernames=["alice"], since_id="100", bridge_done=True)

    outcome = await _service(client, repo)._run_group(state)
    assert outcome.complete is False
    assert set(repo.tweets) == {"201"}
    assert repo.thresholds == [0]
    assert state.since_id == "100"
    assert state.consecutive_stalled_rounds == 1
    assert state.resume_cursor is None


@pytest.mark.asyncio
async def test_complete_round_advances_but_recent_only_round_does_not(monkeypatch):
    _set_page_cap(monkeypatch, 5)
    state = ScrapeGroupState(group_id="g1", usernames=["alice"], since_id="100", bridge_done=True, consecutive_stalled_rounds=2)
    outcome = await _service(FakeClient([Success(_page(_tweet(201)))]))._run_group(state)
    assert outcome.complete is True
    assert state.since_id == "201"
    assert state.consecutive_stalled_rounds == 0

    recent_state = ScrapeGroupState(group_id="g2", usernames=["alice"], since_id="100", bridge_done=True)
    await _service(FakeClient([Success(_page(_tweet(202, minutes_old=1)))]))._run_group(recent_state)
    assert recent_state.since_id == "100"
    assert recent_state.consecutive_stalled_rounds == 0
    assert recent_state.alerts == []


@pytest.mark.asyncio
async def test_page_cap_persists_cursor_and_resume_uses_original_since(monkeypatch):
    _set_page_cap(monkeypatch, 2)
    monkeypatch.setattr("src.scraper.services.incremental_scrape_service.asyncio.sleep", AsyncMock())
    repo = MemoryTweetRepo()
    state = ScrapeGroupState(group_id="g1", usernames=["alice"], since_id="100", bridge_done=True)
    first_client = FakeClient(
        [
            Success(_page(_tweet(500), cursor="c1")),
            Success(_page(_tweet(400), cursor="c2")),
        ]
    )
    first = await _service(first_client, repo)._run_group(state)
    assert first.complete is False
    assert state.since_id == "100"
    assert state.resume_cursor == "c2"
    assert state.resume_since_id == "100"
    assert state.resume_rounds == 1
    assert state.consecutive_stalled_rounds == 0

    state.since_id = "150"
    second_client = FakeClient(
        [
            Success(_page(_tweet(300), cursor="c3")),
            Success(_page(_tweet(200))),
        ]
    )
    await _service(second_client, repo)._run_group(state)
    assert second_client.incremental_calls[0]["cursor"] == "c2"
    assert "since_id:100" in second_client.incremental_calls[0]["query"]
    assert "since_id:150" not in second_client.incremental_calls[0]["query"]
    assert state.resume_cursor is None
    assert state.resume_rounds == 0
    assert state.since_id == "500"
    assert set(repo.tweets) == {"200", "300", "400", "500"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_result",
    [Failure(TwitterClientError("expired cursor")), Success(_page())],
)
async def test_invalid_resume_first_page_clears_continuation_without_stall(monkeypatch, first_result):
    _set_page_cap(monkeypatch, 2)
    state = ScrapeGroupState(
        group_id="g1",
        usernames=["alice"],
        since_id="100",
        bridge_done=True,
        resume_cursor="bad",
        resume_since_id="100",
        resume_rounds=3,
    )
    await _service(FakeClient([first_result]))._run_group(state)
    assert state.resume_cursor is None
    assert state.resume_since_id is None
    assert state.resume_rounds == 0
    assert state.consecutive_stalled_rounds == 0
    assert state.since_id == "100"


@pytest.mark.asyncio
async def test_directional_reconcile_windows_legacy_and_treats_extra_as_clean():
    service = _service(FakeClient())
    state = ScrapeGroupState(group_id="g1", usernames=["alice"], since_id="100", consecutive_clean_rounds=4)
    service._legacy_ids["g1"] = {"50", "101", "102"}
    outcome = await service._reconcile(state, {"101", "102", "103"})
    assert outcome.missing_ids == []
    assert outcome.extra_ids == ["103"]
    assert state.consecutive_clean_rounds == 5

    service._legacy_ids["g1"] = {"101", "102"}
    missing = await service._reconcile(state, {"101"})
    assert missing.missing_ids == ["102"]
    assert state.consecutive_clean_rounds == 0


def test_all_zero_round_emits_actionable_suspected_failure_alert():
    alert = _service(FakeClient())._sentinel_check({"g1": [], "g2": []})
    assert alert is not None
    assert alert.kind == "suspected_query_failure"
    assert alert.group_id == "g1"
    assert set(alert.detail["sentinels"]) == {"GaryMarcus", "levelsio", "elonmusk"}
    assert "建议" in alert.advice


@pytest.mark.asyncio
async def test_bridge_done_is_independent_of_watermark_and_skips_all_api_calls():
    state_repo = Mock()
    state_repo.mark_bridge_started = AsyncMock()
    client = FakeClient(history={"alice": [_page(_tweet(1))]})
    state = ScrapeGroupState(group_id="g1", usernames=["alice"], since_id=None, bridge_done=True)
    await _service(client, state_repo=state_repo)._bridge_backfill(state)
    assert client.history_calls == []
    state_repo.mark_bridge_started.assert_not_awaited()


@pytest.mark.asyncio
async def test_bridge_and_new_account_history_use_separate_limits(monkeypatch):
    monkeypatch.setenv("SCRAPER_INCREMENTAL_BRIDGE_TWEETS", "40")
    monkeypatch.setenv("SCRAPER_INCREMENTAL_NEW_ACCOUNT_BACKFILL_TWEETS", "60")
    clear_settings_cache()
    pages = [_page(*[_tweet(100 - i - j * 20) for i in range(20)]) for j in range(3)]
    client = FakeClient(history={"alice": pages})
    state_repo = Mock()
    state_repo.mark_bridge_started = AsyncMock(return_value=True)
    state = ScrapeGroupState(group_id="g1", usernames=["alice"])
    service = _service(client, state_repo=state_repo)

    await service._bridge_backfill(state)
    assert client.history_calls[-1] == {"username": "alice", "max_pages": 2}
    await service._backfill_new_account(state, "alice")
    assert client.history_calls[-1] == {"username": "alice", "max_pages": 3}
    assert state.backfilled_usernames == ["alice"]


@pytest.mark.asyncio
async def test_dual_round_is_directional_and_persists_one_shared_tweet_set(monkeypatch, tmp_path):
    _set_page_cap(monkeypatch, 5)
    monkeypatch.setenv("SCRAPER_INCREMENTAL_ENABLED", "true")
    clear_settings_cache()
    state_repo = FileScrapeGroupStateStore(tmp_path)
    await state_repo.upsert_group(
        ScrapeGroupState(
            group_id="g1",
            usernames=["alice"],
            since_id="100",
            bridge_done=True,
        )
    )
    repo = MemoryTweetRepo()
    client = FakeClient(
        advanced_results=[Success(_page(_tweet(201), _tweet(202)))],
        legacy=Success(_page(_tweet(201))),
    )

    report = await _service(client, repo, state_repo).run_round(["alice"])
    persisted = (await state_repo.load_all())[0]
    assert report["fetched"] == 2
    assert set(repo.tweets) == {"201", "202"}
    assert persisted.since_id == "202"
    assert persisted.last_reconcile is not None
    assert persisted.last_reconcile.missing == 0
    assert persisted.last_reconcile.extra_ids == ["202"]
    assert persisted.consecutive_clean_rounds == 1
