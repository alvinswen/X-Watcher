"""CHG-040 常规抓取 limit 与 scraper_max_pages_per_scrape 生效契约。"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from returns.result import Failure, Success

from src.scraper.client import TwitterClient, TwitterClientError
from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.scraping_service import ScrapingService
from src.scraper.task_registry import TaskRegistry


def _tweets(page: int, count: int) -> list[Tweet]:
    return [
        Tweet(
            tweet_id=f"p{page}-t{index}",
            text=f"tweet {page}-{index}",
            created_at=datetime.now(UTC),
            author_username="alice",
            author_user_id="uid-alice",
        )
        for index in range(count)
    ]


async def _run_scenario(
    *,
    manual_limit: int | None,
    page_sizes: list[int],
    dynamic_limit: int = 25,
    trigger_limit: int = 100,
    save_outcomes: list[tuple[int, int, int]] | None = None,
    force_next_on_last: bool = False,
) -> tuple[dict, ScrapingService, AsyncMock, list[list[Tweet]]]:
    client = AsyncMock()
    parser = Mock()
    validator = Mock()
    repository = AsyncMock()
    calculator = Mock()
    calculator.calculate_next_limit.return_value = dynamic_limit
    service = ScrapingService(
        client=client,
        parser=parser,
        validator=validator,
        repository=repository,
        limit_calculator=calculator,
    )
    service._get_fetch_stats = AsyncMock(return_value=None)
    service._update_fetch_stats = AsyncMock()
    service._backfill_platform_user_id = AsyncMock()
    service._article_service.fetch_and_save_articles = AsyncMock()

    pages = [_tweets(page, size) for page, size in enumerate(page_sizes, start=1)]
    responses = []
    for index, page_tweets in enumerate(pages):
        has_next = index < len(pages) - 1 or force_next_on_last
        responses.append(
            Success(
                {
                    "data": [{"id": tweet.tweet_id} for tweet in page_tweets],
                    "next_cursor": f"cursor-{index + 2}" if has_next else None,
                }
            )
        )
    client.fetch_user_tweets.side_effect = responses
    parser.parse_tweet_response.side_effect = pages
    validator.validate_and_clean_batch.side_effect = [
        [Success(tweet) for tweet in page_tweets] for page_tweets in pages
    ]

    saved_batches: list[list[Tweet]] = []

    async def save_tweets(tweets, **_kwargs):
        batch = list(tweets)
        saved_batches.append(batch)
        if save_outcomes is None:
            return SaveResult(
                success_count=len(batch),
                skipped_count=0,
                error_count=0,
            )
        success_count, skipped_count, error_count = save_outcomes[
            len(saved_batches) - 1
        ]
        return SaveResult(
            success_count=success_count,
            skipped_count=skipped_count,
            error_count=error_count,
        )

    repository.save_tweets.side_effect = save_tweets

    with patch(
        "src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock
    ):
        result = await service.scrape_single_user(
            "alice",
            limit=trigger_limit,
            manual_limit=manual_limit,
        )

    return result, service, client.fetch_user_tweets, saved_batches


@pytest.mark.asyncio
async def test_e1_manual_limit_5_single_call_truncate(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, _, fetch, saved = await _run_scenario(
        manual_limit=5,
        page_sizes=[20],
        force_next_on_last=True,
    )

    assert fetch.call_count == 1
    assert "cursor" not in fetch.await_args.kwargs
    assert [len(batch) for batch in saved] == [5]
    assert result["discarded_by_limit"] == 15
    assert result["limit_effective"] == 5


@pytest.mark.asyncio
async def test_e2_manual_limit_25_two_calls_cursor(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, _, fetch, saved = await _run_scenario(
        manual_limit=25,
        page_sizes=[20, 20],
    )

    assert fetch.call_count == 2
    assert "cursor" not in fetch.await_args_list[0].kwargs
    assert fetch.await_args_list[1].kwargs["cursor"] == "cursor-2"
    assert [len(batch) for batch in saved] == [20, 5]
    assert result["pages_fetched"] == 2
    assert result["discarded_by_limit"] == 15


@pytest.mark.asyncio
async def test_e3_limit_5_vs_25_observable_diff(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    low, _, low_fetch, low_saved = await _run_scenario(
        manual_limit=5,
        page_sizes=[20],
    )
    high, _, high_fetch, high_saved = await _run_scenario(
        manual_limit=25,
        page_sizes=[20, 20],
    )

    assert (low_fetch.call_count, high_fetch.call_count) == (1, 2)
    assert (sum(map(len, low_saved)), sum(map(len, high_saved))) == (5, 25)
    assert (low["limit_effective"], high["limit_effective"]) == (5, 25)


@pytest.mark.asyncio
async def test_e4_budget_path_dynamic_limit(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, _, fetch, saved = await _run_scenario(
        manual_limit=None,
        dynamic_limit=25,
        trigger_limit=100,
        page_sizes=[20, 20],
    )

    assert fetch.call_count == 2
    assert fetch.await_args_list[1].kwargs["cursor"] == "cursor-2"
    assert sum(map(len, saved)) == 25
    assert result["limit_effective"] == 25
    assert result["discarded_by_limit"] == 15


@pytest.mark.asyncio
async def test_first_page_404_rename_heal():
    client = AsyncMock()
    client.fetch_user_tweets.side_effect = [
        Failure(TwitterClientError("not found", status_code=404)),
        Success({"data": [], "next_cursor": None}),
    ]
    service = ScrapingService(
        client=client,
        parser=Mock(parse_tweet_response=Mock(return_value=[])),
        validator=Mock(),
        repository=AsyncMock(),
        limit_calculator=Mock(calculate_next_limit=Mock(return_value=5)),
    )
    service._get_fetch_stats = AsyncMock(return_value=None)
    service._update_fetch_stats = AsyncMock()
    service._profile_service.detect_and_fix_rename = AsyncMock(
        return_value="alice_new"
    )

    result = await service.scrape_single_user("alice", manual_limit=5)

    assert result["success"] is True
    assert result["username"] == "alice_new"
    assert [item.args[0] for item in client.fetch_user_tweets.await_args_list] == [
        "alice",
        "alice_new",
    ]
    service._profile_service.detect_and_fix_rename.assert_awaited_once_with("alice")


@pytest.mark.asyncio
async def test_mid_page_failure_keeps_partial(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    client = AsyncMock()
    first_page = _tweets(1, 20)
    client.fetch_user_tweets.side_effect = [
        Success(
            {
                "data": [{"id": tweet.tweet_id} for tweet in first_page],
                "next_cursor": "cursor-2",
            }
        ),
        Failure(TwitterClientError("upstream unavailable", status_code=503)),
    ]
    parser = Mock(parse_tweet_response=Mock(return_value=first_page))
    validator = Mock(
        validate_and_clean_batch=Mock(
            return_value=[Success(tweet) for tweet in first_page]
        )
    )
    repository = AsyncMock()
    repository.save_tweets.return_value = SaveResult(
        success_count=20,
        skipped_count=0,
        error_count=0,
    )
    service = ScrapingService(
        client=client,
        parser=parser,
        validator=validator,
        repository=repository,
        limit_calculator=Mock(calculate_next_limit=Mock(return_value=25)),
    )
    service._get_fetch_stats = AsyncMock(return_value=None)
    service._update_fetch_stats = AsyncMock()
    service._backfill_platform_user_id = AsyncMock()
    service._article_service.fetch_and_save_articles = AsyncMock()

    with patch(
        "src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock
    ):
        result = await service.scrape_single_user("alice", manual_limit=25)

    assert result["success"] is True
    assert result["new"] == 20
    assert result["errors"] == 1
    assert result["pages_fetched"] == 1
    assert "翻页第 2 页失败: upstream unavailable" in result["error_message"]


@pytest.mark.asyncio
async def test_actual_limit_below_1_account_fail():
    client = TwitterClient()
    network_call = AsyncMock()
    client._fetch_with_retry = network_call
    service = ScrapingService(
        client=client,
        parser=Mock(),
        validator=Mock(),
        repository=AsyncMock(),
        limit_calculator=Mock(calculate_next_limit=Mock(return_value=25)),
    )
    service._get_fetch_stats = AsyncMock(return_value=None)

    result = await service.scrape_single_user("alice", limit=0)

    assert result["success"] is False
    assert result["errors"] == 1
    assert result["error_message"] == "limit 必须大于 0"
    network_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_r1_pages_by_conversion_not_full_page(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, _, fetch, saved = await _run_scenario(
        manual_limit=21,
        page_sizes=[20, 20],
    )

    assert fetch.call_count == 2
    assert sum(map(len, saved)) == 21
    assert result["pages_fetched"] == 2
    assert result["limit_capped"] is False


@pytest.mark.asyncio
async def test_r2_double_after_truncated_full_fetch(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, service, _, _ = await _run_scenario(
        manual_limit=5,
        page_sizes=[20],
    )

    stats_call = service._update_fetch_stats.await_args
    assert stats_call.kwargs["fetched_count"] == 5
    assert stats_call.kwargs["new_count"] == 5

    calculator = __import__(
        "src.scraper.services.limit_calculator",
        fromlist=["LimitCalculator"],
    ).LimitCalculator(default_limit=5, min_limit=5, max_limit=300)
    stats = calculator.update_stats_after_fetch(
        stats=None,
        username="alice",
        fetched_count=stats_call.kwargs["fetched_count"],
        new_count=stats_call.kwargs["new_count"],
    )
    assert calculator.calculate_next_limit(stats) > result["limit_effective"]


@pytest.mark.asyncio
async def test_page_budget_conversion_boundaries(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    scenarios = (
        (1, [20], 1),
        (20, [20], 1),
        (21, [20, 20], 2),
        (200, [20] * 10, 10),
    )

    for limit, pages, expected_calls in scenarios:
        result, _, fetch, _ = await _run_scenario(
            manual_limit=limit,
            page_sizes=pages,
        )
        assert fetch.call_count == expected_calls
        assert result["pages_fetched"] == expected_calls
        assert result["limit_capped"] is False


@pytest.mark.asyncio
async def test_manual_1000_capped_honest(monkeypatch, caplog):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    with caplog.at_level("INFO", logger="src.scraper.scraping_service"):
        result, _, fetch, saved = await _run_scenario(
            manual_limit=1000,
            page_sizes=[20] * 10,
            force_next_on_last=True,
        )

    assert fetch.call_count == 10
    assert sum(map(len, saved)) == 200
    assert result["limit_effective"] == 1000
    assert result["pages_fetched"] == 10
    assert result["limit_capped"] is True
    assert "预算页数已被总闸封顶" in caplog.text
    assert "limit=1000 已生效" not in caplog.text


@pytest.mark.asyncio
async def test_result_new_four_fields(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, service, _, _ = await _run_scenario(
        manual_limit=5,
        page_sizes=[3],
    )

    assert isinstance(result["limit_effective"], int)
    assert isinstance(result["pages_fetched"], int)
    assert isinstance(result["limit_capped"], bool)
    assert isinstance(result["discarded_by_limit"], int)

    summary = service._summarize_results(["alice"], [result])
    user_result = summary["user_results"][0]
    assert {
        "limit_effective",
        "pages_fetched",
        "limit_capped",
        "discarded_by_limit",
    } <= user_result.keys()

    service._scrape_with_semaphore = AsyncMock(return_value=result)
    service._profile_service.sync_user_profiles = AsyncMock()
    task_id = await service.scrape_users(
        ["alice"],
        manual_limits={"alice": 5},
    )
    final_report = TaskRegistry.get_instance().get_task_status(task_id)["result"]
    assert set(final_report) == {
        "total_users",
        "successful_users",
        "failed_users",
        "total_tweets",
        "new_tweets",
        "skipped_tweets",
        "total_errors",
        "elapsed_seconds",
    }


@pytest.mark.asyncio
async def test_empty_page_stats(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    result, service, fetch, saved = await _run_scenario(
        manual_limit=5,
        page_sizes=[0],
    )

    assert fetch.call_count == 1
    assert saved == []
    assert result["success"] is True
    assert result["pages_fetched"] == 1
    service._update_fetch_stats.assert_awaited_once_with(
        username="alice",
        old_stats=None,
        fetched_count=0,
        new_count=0,
    )


@pytest.mark.asyncio
async def test_skip_rate_early_stop(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    high, _, high_fetch, _ = await _run_scenario(
        manual_limit=40,
        page_sizes=[20, 0],
        save_outcomes=[(3, 17, 0)],
    )
    boundary, _, boundary_fetch, _ = await _run_scenario(
        manual_limit=40,
        page_sizes=[20, 0],
        save_outcomes=[(4, 16, 0)],
    )

    assert high_fetch.call_count == 1
    assert high["pages_fetched"] == 1
    assert boundary_fetch.call_count == 2
    assert boundary["pages_fetched"] == 2
