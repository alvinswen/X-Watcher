"""CHG-054 disabled-switch parity guard for the legacy scrape path."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from returns.result import Success

from src.config import clear_settings_cache
from src.scraper.scraping_service import ScrapingService


@pytest.mark.asyncio
async def test_disabled_switch_never_constructs_or_calls_incremental_path(monkeypatch):
    monkeypatch.setenv("SCRAPER_INCREMENTAL_ENABLED", "false")
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    clear_settings_cache()

    client = Mock()
    client.fetch_user_tweets = AsyncMock(
        return_value=Success({"data": [], "includes": {}, "next_cursor": None})
    )
    client.search_tweets_incremental = AsyncMock()
    client.close = AsyncMock()
    repository = Mock()
    service = ScrapingService(client=client, repository=repository)
    service._registry = Mock()
    service._profile_service.sync_user_profiles = AsyncMock()
    service._get_fetch_stats = AsyncMock(return_value=None)
    service._update_fetch_stats = AsyncMock()

    with patch(
        "src.scraper.services.incremental_scrape_service.IncrementalScrapeService.__init__",
        return_value=None,
    ) as incremental_init:
        first = await service.scrape_users(
            ["alice"], task_id="same-task", limit=5, manual_limits={}
        )
        first_report = service._registry.update_task_status.call_args_list[-1]
        service._registry.reset_mock()
        second = await service.scrape_users(
            ["alice"], task_id="same-task", limit=5, manual_limits={}
        )
        second_report = service._registry.update_task_status.call_args_list[-1]

    assert first == second == "same-task"
    assert first_report == second_report
    incremental_init.assert_not_called()
    client.search_tweets_incremental.assert_not_awaited()
