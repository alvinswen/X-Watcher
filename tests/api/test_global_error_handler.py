"""CHG-037 全局 REST 错误兜底与框架放行链。"""

import logging

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.main import app
from src.shared.error_messages import INTERNAL_SERVER_ERROR_DETAIL


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
