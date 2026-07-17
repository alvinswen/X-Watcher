"""CHG-033 service extraction and orchestration wiring guards."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from returns.result import Failure, Success

from src.scraper.client import TwitterClientError
from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.scraping_service import ScrapingService


def _service(client: AsyncMock | None = None) -> ScrapingService:
    limit_calculator = Mock()
    limit_calculator.calculate_next_limit.return_value = 5
    return ScrapingService(
        client=client or AsyncMock(),
        parser=Mock(),
        validator=Mock(),
        repository=AsyncMock(),
        limit_calculator=limit_calculator,
    )


@pytest.mark.asyncio
async def test_tc_build_444_scrape_users_delegates_profile_sync() -> None:
    """The batch orchestration retains the extracted profile-sync call."""
    service = _service()
    service._registry = Mock()
    service._scrape_with_semaphore = AsyncMock(
        return_value={
            "username": "alice",
            "success": True,
            "fetched": 0,
            "new": 0,
            "skipped": 0,
            "errors": 0,
            "error_message": None,
        }
    )
    service._profile_service.sync_user_profiles = AsyncMock()

    await service.scrape_users(
        ["alice"],
        task_id="chg033-profile-sync",
        manual_limits={},
    )

    service._profile_service.sync_user_profiles.assert_awaited_once_with(["alice"])


@pytest.mark.asyncio
async def test_tc_build_445_rename_retry_delegates_profile_service() -> None:
    """A first-attempt 404 still performs rename repair before retrying."""
    client = AsyncMock()
    client.fetch_user_tweets = AsyncMock(
        return_value=Failure(TwitterClientError("not found", status_code=404))
    )
    service = _service(client)
    service._get_fetch_stats = AsyncMock(return_value={})
    service._profile_service.detect_and_fix_rename = AsyncMock(return_value="alice-new")
    retry_result = {"username": "alice-new", "success": True}
    service.scrape_single_user = AsyncMock(return_value=retry_result)
    initial_result = {
        "username": "alice",
        "success": False,
        "fetched": 0,
        "new": 0,
        "skipped": 0,
        "errors": 0,
        "error_message": None,
    }

    result = await service._scrape_single_user_inner(
        "alice",
        result=initial_result,
        limit=100,
        manual_limit=7,
    )

    assert result is retry_result
    service._profile_service.detect_and_fix_rename.assert_awaited_once_with("alice")
    service.scrape_single_user.assert_awaited_once_with(
        "alice-new",
        limit=100,
        manual_limit=7,
        _retry_count=1,
    )


@pytest.mark.asyncio
async def test_tc_build_442_live_scrape_delegates_article_fetch() -> None:
    """A successfully cleaned live tweet reaches the extracted Article service."""
    tweet = Tweet(
        tweet_id="tweet-live",
        text="article candidate",
        created_at=datetime.now(),
        author_username="alice",
    )
    client = AsyncMock()
    client.fetch_user_tweets = AsyncMock(return_value=Success({"data": []}))
    service = _service(client)
    service._get_fetch_stats = AsyncMock(return_value=None)
    service._parser.parse_tweet_response.return_value = [tweet]
    service._validator.validate_and_clean_batch.return_value = [Success(tweet)]
    service._save_tweets = AsyncMock(
        return_value=SaveResult(success_count=1, skipped_count=0, error_count=0)
    )
    service._update_fetch_stats = AsyncMock()
    service._article_service.fetch_and_save_articles = AsyncMock()
    result = {
        "username": "alice",
        "success": False,
        "fetched": 0,
        "new": 0,
        "skipped": 0,
        "errors": 0,
        "error_message": None,
    }

    await service._scrape_single_user_inner("alice", result=result)

    service._article_service.fetch_and_save_articles.assert_awaited_once_with([tweet])


@pytest.mark.asyncio
async def test_tc_build_443_history_backfill_delegates_article_fetch() -> None:
    """Every persisted backfill page retains its Article service call."""
    tweet = Tweet(
        tweet_id="tweet-backfill",
        text="historical candidate",
        created_at=datetime.now(),
        author_username="alice",
    )
    client = AsyncMock()

    async def pages(username: str, *, max_pages: int = 10, page_delay: float = 1.0):
        yield {"data": [{"id": "tweet-backfill"}]}

    client.fetch_user_tweets_paginated = pages
    service = _service(client)
    service._parser.parse_tweet_response.return_value = [tweet]
    service._validator.validate_and_clean_batch.return_value = [Success(tweet)]
    service._save_tweets = AsyncMock(
        return_value=SaveResult(success_count=1, skipped_count=0, error_count=0)
    )
    service._update_backfill_status = AsyncMock()
    service._article_service.fetch_and_save_articles = AsyncMock()

    result = await service.backfill_user("alice", max_pages=1)

    assert result["success"] is True
    service._article_service.fetch_and_save_articles.assert_awaited_once_with([tweet])


@pytest.mark.asyncio
async def test_tc_build_446_orchestrator_owns_one_shared_client_close() -> None:
    """Both child services share the orchestrator client, which closes once."""
    client = AsyncMock()
    client.close = AsyncMock()
    service = _service(client)

    assert service._article_service._client is client
    assert service._profile_service._client is client

    await service.close()

    client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_tc_build_447_rest_article_service_is_constructed_and_closed() -> None:
    """The single-user REST path owns an independent Article service lifecycle."""
    from src.api.routes.admin import BackfillRequest, backfill_articles

    service = Mock()
    service.backfill_articles_for_user = AsyncMock(return_value={"checked": 1})
    service.close = AsyncMock()
    admin = Mock()
    admin.name = "admin"

    with (
        patch("src.api.routes.admin.get_article_fetch_service", return_value=service) as factory,
        patch("src.api.routes.admin.audit_log"),
    ):
        result = await backfill_articles(
            BackfillRequest(username="alice", max_tweets=20),
            admin,
        )

    assert result.model_dump() == {
        "username": "alice",
        "result": {"checked": 1},
    }
    factory.assert_called_once_with()
    service.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_tc_build_449_rest_close_failure_is_fail_soft(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An Article close failure logs a warning without replacing success."""
    from src.api.routes.admin import BackfillRequest, backfill_articles

    service = Mock()
    service.backfill_articles_for_user = AsyncMock(return_value={"checked": 2})
    service.close = AsyncMock(side_effect=RuntimeError("close failed"))
    admin = Mock()
    admin.name = "admin"

    with (
        patch("src.api.routes.admin.get_article_fetch_service", return_value=service),
        patch("src.api.routes.admin.audit_log"),
        caplog.at_level("WARNING"),
    ):
        result = await backfill_articles(
            BackfillRequest(username="alice", max_tweets=20),
            admin,
        )

    assert result.model_dump() == {
        "username": "alice",
        "result": {"checked": 2},
    }
    assert "关闭 ArticleFetchService 连接失败" in caplog.text
