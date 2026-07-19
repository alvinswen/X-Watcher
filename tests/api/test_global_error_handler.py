"""CHG-037 全局 REST 错误兜底与框架放行链。"""

import logging
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.main import app
from src.shared.error_messages import (
    ARTICLE_BACKFILL_FAILED,
    INTERNAL_SERVER_ERROR_DETAIL,
    SUMMARY_QUERY_FAILED,
    TWEETS_DETAIL_QUERY_FAILED,
    TWEETS_LIST_QUERY_FAILED,
)


class _ValidationPayload(BaseModel):
    value: int


async def _raise_unhandled() -> None:
    raise RuntimeError("chg037-sensitive-internal-error")


async def _raise_http_exception() -> None:
    raise HTTPException(status_code=409, detail="已知业务冲突")


async def _validate_payload(payload: _ValidationPayload) -> dict[str, int]:
    return {"value": payload.value}


app.add_api_route(
    "/api/_test/chg037/unhandled",
    _raise_unhandled,
    methods=["GET"],
    include_in_schema=False,
)
app.add_api_route(
    "/api/_test/chg037/http-exception",
    _raise_http_exception,
    methods=["GET"],
    include_in_schema=False,
)
app.add_api_route(
    "/api/_test/chg037/validation",
    _validate_payload,
    methods=["POST"],
    include_in_schema=False,
)


def test_unhandled_exception_returns_fixed_json_and_logs_traceback(caplog) -> None:
    with (
        caplog.at_level(logging.ERROR, logger="src.main"),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/api/_test/chg037/unhandled")

    assert response.status_code == 500
    assert response.json() == {"detail": INTERNAL_SERVER_ERROR_DETAIL}
    assert "chg037-sensitive-internal-error" not in response.text
    record = next(record for record in caplog.records if "未捕获异常" in record.message)
    assert record.exc_info is not None
    assert "chg037-sensitive-internal-error" in caplog.text


def test_http_exception_keeps_status_and_curated_detail() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/_test/chg037/http-exception")

    assert response.status_code == 409
    assert response.json() == {"detail": "已知业务冲突"}


def test_request_validation_error_keeps_default_detail_array() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/_test/chg037/validation", json={"value": "not-an-int"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


async def test_list_tweets_hides_internal_error_and_logs_traceback(
    async_client,
    monkeypatch,
    caplog,
) -> None:
    repo = MagicMock()
    repo.list_tweets = AsyncMock(side_effect=RuntimeError("tweets-list-secret"))
    monkeypatch.setattr("src.data_layer.provider.get_tweet_read_repo", lambda: repo)

    with caplog.at_level(logging.ERROR, logger="src.api.routes.tweets"):
        response = await async_client.get("/api/tweets")

    assert response.status_code == 500
    assert response.json() == {"detail": TWEETS_LIST_QUERY_FAILED}
    assert "tweets-list-secret" not in response.text
    assert "tweets-list-secret" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)


async def test_tweet_detail_hides_internal_error(async_client, monkeypatch) -> None:
    repo = MagicMock()
    repo.get_tweet_detail = AsyncMock(side_effect=RuntimeError("tweets-detail-secret"))
    monkeypatch.setattr("src.data_layer.provider.get_tweet_read_repo", lambda: repo)

    response = await async_client.get("/api/tweets/tweet-1")

    assert response.status_code == 500
    assert response.json() == {"detail": TWEETS_DETAIL_QUERY_FAILED}
    assert "tweets-detail-secret" not in response.text


async def test_summary_hides_internal_error(async_client, monkeypatch) -> None:
    repo = MagicMock()
    repo.get_summary_by_tweet = AsyncMock(side_effect=RuntimeError("summary-secret"))
    monkeypatch.setattr("src.summarization.api.routes.get_summary_repo", lambda: repo)

    response = await async_client.get("/api/summaries/tweets/tweet-1")

    assert response.status_code == 500
    assert response.json() == {"detail": SUMMARY_QUERY_FAILED}
    assert "summary-secret" not in response.text


async def test_article_backfill_hides_internal_error_and_closes_service(
    async_client,
    monkeypatch,
) -> None:
    service = MagicMock()
    service.backfill_articles_for_user = AsyncMock(side_effect=RuntimeError("article-secret"))
    service.close = AsyncMock()
    monkeypatch.setattr(
        "src.api.routes.admin.get_article_fetch_service",
        lambda: service,
    )

    response = await async_client.post(
        "/api/admin/articles/backfill",
        json={"username": "alice", "max_tweets": 10},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": ARTICLE_BACKFILL_FAILED}
    assert "article-secret" not in response.text
    service.close.assert_awaited_once()
