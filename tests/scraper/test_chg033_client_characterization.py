"""CHG-033 TwitterClient behavior characterization tests.

These tests intentionally run against the B1.29.0 baseline before the retry
and response-conversion code is extracted. They pin the observable behavior
that the refactor must preserve.
"""

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from returns.result import Failure, Success

from src.scraper import client as client_module
from src.scraper.client import TwitterClient


def _response(status_code: int, payload: object | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    if payload is not None:
        response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_tc_build_433_account_info_keeps_two_local_retries(
    test_settings,
) -> None:
    """Account-info polling uses two retries, not the client default."""
    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=_response(500))
    client = TwitterClient(max_retries=5, base_delay=1, max_delay=8)

    with (
        patch("httpx.AsyncClient", return_value=http_client),
        patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        result = await client.fetch_account_info()

    assert isinstance(result, Failure)
    assert result.failure().message == "API 错误 500: 已达到最大重试次数"
    assert http_client.get.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]
    http_client.get.assert_awaited_with("https://api.twitterapi.io/oapi/my/info")


@pytest.mark.asyncio
async def test_tc_build_434_user_info_retry_backoff_without_circuit_breaker(
    test_settings,
) -> None:
    """Batch user-info retries follow client settings and bypass the breaker."""
    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=_response(500))
    client = TwitterClient(max_retries=2, base_delay=0.25, max_delay=1)

    with (
        patch("httpx.AsyncClient", return_value=http_client),
        patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock) as sleep,
        patch.object(client_module._circuit_breaker, "record_success") as success,
        patch.object(client_module._circuit_breaker, "record_failure") as failure,
    ):
        result = await client.fetch_user_info_by_ids(["10", "20"])

    assert isinstance(result, Failure)
    assert result.failure().message == "API 错误 500: 已达到最大重试次数"
    assert http_client.get.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 0.5]
    http_client.get.assert_awaited_with(
        "/user/batch_info_by_ids",
        params={"userIds": "10,20"},
    )
    success.assert_not_called()
    failure.assert_not_called()


@pytest.mark.asyncio
async def test_tc_build_435_article_retry_and_non_retryable_paths(
    test_settings,
) -> None:
    """Article lookup retries server errors but stops immediately on 404."""
    retrying_http_client = AsyncMock()
    retrying_http_client.get = AsyncMock(
        side_effect=[
            _response(500),
            _response(500),
            _response(200, {"data": {"title": "kept"}}),
        ]
    )
    retrying_client = TwitterClient(max_retries=2, base_delay=1, max_delay=4)

    with (
        patch("httpx.AsyncClient", return_value=retrying_http_client),
        patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock) as sleep,
        patch.object(client_module._circuit_breaker, "record_success") as success,
        patch.object(client_module._circuit_breaker, "record_failure") as failure,
    ):
        retry_result = await retrying_client.fetch_article("tweet-1")

    assert isinstance(retry_result, Success)
    assert retry_result.unwrap() == {"data": {"title": "kept"}}
    assert retrying_http_client.get.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]
    success.assert_not_called()
    failure.assert_not_called()

    non_retrying_http_client = AsyncMock()
    non_retrying_http_client.get = AsyncMock(return_value=_response(404))
    non_retrying_client = TwitterClient(max_retries=5)
    with patch("httpx.AsyncClient", return_value=non_retrying_http_client):
        non_retry_result = await non_retrying_client.fetch_article("missing")

    assert isinstance(non_retry_result, Failure)
    assert non_retry_result.failure().message == "API 错误 404: 资源未找到"
    assert non_retrying_http_client.get.await_count == 1


@pytest.mark.asyncio
async def test_tc_build_439_inline_conversion_characterization(
    test_settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pin nested references, media, users, cursor, and truncation behavior."""
    raw_response = {
        "data": {
            "next_cursor": "cursor-2",
            "tweets": [
                {
                    "id": "rt-1",
                    "text": "retweet wrapper",
                    "createdAt": "Fri Feb 06 09:31:48 +0000 2026",
                    "retweeted_tweet": {
                        "id": "source-1",
                        "full_text": "possibly truncated...",
                        "media": [
                            {
                                "id_str": "ref-media",
                                "type": "photo",
                                "media_url_https": "https://example.test/ref.jpg",
                                "width": 640,
                                "height": 480,
                            }
                        ],
                        "author": {"userName": "source_user"},
                    },
                    "media": [
                        {
                            "id_str": "main-media",
                            "type": "photo",
                            "media_url_https": "https://example.test/main.jpg",
                            "width": 320,
                            "height": 240,
                        }
                    ],
                    "author": {"id": "u1", "userName": "retweeter", "name": "RT"},
                    "article": {"title": "Article stays"},
                },
                {
                    "id": "quote-1",
                    "text": "quote wrapper",
                    "createdAt": "Fri Feb 06 10:31:48 +0000 2026",
                    "quoted_tweet": {
                        "id": "source-2",
                        "note_tweet": {"text": "complete quoted text"},
                        "author": {"userName": "quoted_user"},
                    },
                    "author": {"id": "u2", "userName": "quoter", "name": "Quote"},
                },
                {
                    "id": "reply-1",
                    "text": "reply",
                    "createdAt": "Fri Feb 06 11:31:48 +0000 2026",
                    "isReply": True,
                    "inReplyToId": "source-3",
                    "author": {"id": "u3", "userName": "replier", "name": "Reply"},
                },
                {
                    "id": "original-1",
                    "text": "short",
                    "note_tweet": {"text": "the complete original text"},
                    "createdAt": "Fri Feb 06 12:31:48 +0000 2026",
                    "author": {"id": "u4", "userName": "original", "name": "Original"},
                },
            ],
        }
    }
    http_client = AsyncMock()
    http_client.get = AsyncMock(return_value=_response(200, raw_response))
    client = TwitterClient()

    caplog.set_level(logging.WARNING, logger="src.scraper.client")
    with (
        patch("httpx.AsyncClient", return_value=http_client),
        patch.object(client_module._circuit_breaker, "allow_request", return_value=True),
    ):
        result = await client.fetch_user_tweets("characterization")

    assert isinstance(result, Success)
    assert result.unwrap() == {
        "data": [
            {
                "id": "rt-1",
                "text": "retweet wrapper",
                "created_at": "2026-02-06T09:31:48.000Z",
                "referenced_tweets": [{"type": "retweeted", "id": "source-1"}],
                "referenced_tweet_text": "possibly truncated...",
                "referenced_tweet_media": [
                    {
                        "media_key": "ref-media",
                        "type": "photo",
                        "url": "https://example.test/ref.jpg",
                        "preview_image_url": None,
                        "width": 640,
                        "height": 480,
                        "alt_text": None,
                    }
                ],
                "referenced_tweet_author_username": "source_user",
                "attachments": {"media_keys": ["main-media"]},
                "author_id": "u1",
                "article": {"title": "Article stays"},
            },
            {
                "id": "quote-1",
                "text": "quote wrapper",
                "created_at": "2026-02-06T10:31:48.000Z",
                "referenced_tweets": [{"type": "quoted", "id": "source-2"}],
                "referenced_tweet_text": "complete quoted text",
                "referenced_tweet_author_username": "quoted_user",
                "author_id": "u2",
            },
            {
                "id": "reply-1",
                "text": "reply",
                "created_at": "2026-02-06T11:31:48.000Z",
                "referenced_tweets": [{"type": "replied_to", "id": "source-3"}],
                "author_id": "u3",
            },
            {
                "id": "original-1",
                "text": "the complete original text",
                "created_at": "2026-02-06T12:31:48.000Z",
                "author_id": "u4",
            },
        ],
        "includes": {
            "users": [
                {"id": "u1", "username": "retweeter", "name": "RT", "numeric_id": "u1"},
                {"id": "u2", "username": "quoter", "name": "Quote", "numeric_id": "u2"},
                {"id": "u3", "username": "replier", "name": "Reply", "numeric_id": "u3"},
                {"id": "u4", "username": "original", "name": "Original", "numeric_id": "u4"},
            ],
            "media": [
                {
                    "media_key": "main-media",
                    "type": "photo",
                    "url": "https://example.test/main.jpg",
                    "preview_image_url": None,
                    "width": 320,
                    "height": 240,
                    "alt_text": None,
                }
            ],
        },
        "next_cursor": "cursor-2",
    }
    assert client_module._convert_twitterapi_response(raw_response) == result.unwrap()
    assert "嵌套推文文本疑似被截断" in caplog.text
