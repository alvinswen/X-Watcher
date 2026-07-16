"""CHG-033 structural guards for the TwitterClient refactor."""

import inspect
from unittest.mock import AsyncMock, Mock, patch

import pytest
from returns.result import Failure, Success

from src.scraper import client as client_module
from src.scraper.client import TwitterClient


def _response(payload: object) -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_tc_build_436_only_tweet_fetch_uses_circuit_breaker(
    test_settings,
) -> None:
    """The shared retry helper must not spread breaker accounting."""
    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=_response({"users": []}))
    client = TwitterClient()

    with (
        patch("httpx.AsyncClient", return_value=http_client),
        patch.object(client_module._circuit_breaker, "allow_request", return_value=True) as allow,
        patch.object(client_module._circuit_breaker, "record_success") as success,
        patch.object(client_module._circuit_breaker, "record_failure") as failure,
    ):
        tweet_result = await client.fetch_user_tweets("breaker-owner")
        article_result = await client.fetch_article("tweet-1")
        users_result = await client.fetch_user_info_by_ids(["user-1"])
        account_result = await client.fetch_account_info()

    assert isinstance(tweet_result, Success)
    assert isinstance(article_result, Success)
    assert isinstance(users_result, Success)
    assert isinstance(account_result, Success)
    allow.assert_called_once_with()
    success.assert_called_once_with()
    failure.assert_not_called()


@pytest.mark.asyncio
async def test_tc_build_437_value_error_branch_stays_local_to_tweet_inner(
    test_settings,
) -> None:
    """The public helper catches generic errors without a ValueError branch."""
    helper_source = inspect.getsource(TwitterClient._request_with_retry)
    inner_source = inspect.getsource(TwitterClient._fetch_with_retry_inner)
    assert "except ValueError" not in helper_source
    assert "except ValueError" in inner_source

    response = _response({})
    response.json.side_effect = ValueError("broken-json")
    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=response)

    article_client = TwitterClient()
    with patch("httpx.AsyncClient", return_value=http_client):
        article_result = await article_client.fetch_article("tweet-1")

    assert isinstance(article_result, Failure)
    assert article_result.failure().message == "未预期的错误: broken-json"

    tweet_client = TwitterClient()
    with (
        patch("httpx.AsyncClient", return_value=http_client),
        patch.object(client_module._circuit_breaker, "allow_request", return_value=True),
    ):
        tweet_result = await tweet_client.fetch_user_tweets("tweet-json")

    assert isinstance(tweet_result, Failure)
    assert tweet_result.failure().message == "响应处理失败: broken-json"


def test_tc_build_440_conversion_boundaries_are_identity_preserving() -> None:
    """Already-normalized and empty payloads are returned unchanged."""
    normalized = {"data": [{"id": "tweet-1", "text": "kept"}]}
    empty: dict[str, object] = {}

    assert client_module._convert_twitterapi_response(normalized) is normalized
    assert client_module._convert_twitterapi_response(empty) is empty


@pytest.mark.asyncio
async def test_tc_build_448_twitter_client_close_is_idempotent(
    test_settings,
) -> None:
    """Closing twice closes the one underlying client exactly once."""
    http_client = AsyncMock()
    client = TwitterClient()

    with patch("httpx.AsyncClient", return_value=http_client):
        client._ensure_client()
        await client.close()
        await client.close()

    http_client.aclose.assert_awaited_once_with()
    assert client._client is None
