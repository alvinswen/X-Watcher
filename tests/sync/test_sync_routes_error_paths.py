"""CHG-037 L2 解析与管理员业务拒绝错误路径。"""

import json
import logging
from datetime import timezone

import pytest
from fastapi import HTTPException

from src.api.routes.sync_routes import _parse_upload_file
from src.data_layer.provider import get_user_repo
from src.search.api.routes import _parse_time_param
from src.shared.error_messages import (
    SEARCH_TIME_FORMAT_INVALID_TMPL,
    SYNC_EXPORT_FILE_MISSING_FIELD_TMPL,
    SYNC_EXPORT_FILE_PARSE_FAILED,
    USER_LAST_ADMIN_DEMOTE_REFUSED,
)


def test_bad_json_reports_line_and_column_without_parser_message() -> None:
    with pytest.raises(HTTPException) as caught:
        _parse_upload_file(b'{\n  "metadata":,\n  "data": {}\n}')

    assert caught.value.status_code == 400
    detail = caught.value.detail
    assert "文件第 2 行第 14 列附近" in detail
    assert "Expecting value" not in detail


def test_missing_export_field_reports_field_name() -> None:
    content = json.dumps(
        {
            "metadata": {"schema_version": 1},
            "data": {},
        }
    ).encode()

    with pytest.raises(HTTPException) as caught:
        _parse_upload_file(content)

    assert caught.value.status_code == 400
    assert caught.value.detail == SYNC_EXPORT_FILE_MISSING_FIELD_TMPL.format(field="exported_at")


def test_invalid_export_shape_uses_fixed_message_and_logs_original(caplog) -> None:
    content = json.dumps(
        {
            "metadata": {
                "schema_version": 1,
                "exported_at": "not-a-datetime",
            },
            "data": {},
        }
    ).encode()

    with (
        caplog.at_level(logging.WARNING, logger="src.api.routes.sync_routes"),
        pytest.raises(HTTPException) as caught,
    ):
        _parse_upload_file(content)

    assert caught.value.status_code == 400
    assert caught.value.detail == SYNC_EXPORT_FILE_PARSE_FAILED
    assert "not-a-datetime" not in str(caught.value.detail)
    assert "导出文件解析失败" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)


def test_search_time_error_keeps_422_and_parameter_context() -> None:
    raw = "not-a-date"

    with pytest.raises(HTTPException) as caught:
        _parse_time_param("since", raw)

    assert caught.value.status_code == 422
    assert caught.value.detail == SEARCH_TIME_FORMAT_INVALID_TMPL.format(
        name="since",
        value=raw,
    )
    assert "Invalid isoformat string" not in caught.value.detail


def test_search_time_without_timezone_defaults_to_utc() -> None:
    parsed = _parse_time_param("since", "2026-01-01T00:00:00")

    assert parsed.tzinfo is timezone.utc


async def test_last_admin_demotion_keeps_exact_detail_and_user_state(
    async_client,
    caplog,
) -> None:
    repo = get_user_repo()
    user = await repo.create_user("only-admin", "only-admin@example.com", "hash")
    await repo.update_user(user.id, is_admin=True)

    with caplog.at_level(logging.WARNING, logger="src.user.api.admin_user_router"):
        response = await async_client.put(
            f"/api/admin/users/{user.id}",
            json={"is_admin": False},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": USER_LAST_ADMIN_DEMOTE_REFUSED}
    stored = await repo.get_user_by_id(user.id)
    assert stored is not None
    assert stored.is_admin is True
    assert f"user_id={user.id}" in caplog.text
    assert USER_LAST_ADMIN_DEMOTE_REFUSED in caplog.text
