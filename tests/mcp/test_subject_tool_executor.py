from __future__ import annotations

import json
from unittest.mock import AsyncMock, call, patch

import pytest

from src.mcp.server import create_mcp_server


def _tool_funcs():
    mcp = create_mcp_server()
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def _decode(result: str) -> dict:
    return json.loads(result)


@pytest.mark.asyncio
async def test_six_read_tools_record_success_audits():
    repo = AsyncMock()
    repo.list_subjects.return_value = []
    repo.get_subject.return_value = object()
    repo.get_subject_feed.return_value = {"items": [], "count": 0}
    repo.get_digest.return_value = None
    repo.get_review.return_value = None
    repo.get_updates.return_value = {"items": [], "next_cursor": None}
    repo.get_tweets_by_ids.return_value = ([], [])
    tools = _tool_funcs()

    with (
        patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo),
        patch("src.mcp.tools.subject_tools.audit_log") as audit_log,
    ):
        results = [
            await tools["list_subjects"](),
            await tools["get_subject_feed"](subject_id="sub_test"),
            await tools["get_subject_digest"](subject_id="sub_test"),
            await tools["get_subject_review"](subject_id="sub_test"),
            await tools["get_subject_updates"](),
            await tools["get_tweets_by_ids"](tweet_ids="tw_1"),
        ]

    assert all(_decode(result)["success"] is True for result in results)
    expected = [
        call("list_subjects", "read", params={"status": None}),
        call("get_subject_feed", "read", params={"subject_id": "sub_test"}),
        call("get_subject_digest", "read", params={"subject_id": "sub_test"}),
        call("get_subject_review", "read", params={"subject_id": "sub_test"}),
        call("get_subject_updates", "read", params={"since_cursor": None}),
        call("get_tweets_by_ids", "read", params={"tweet_ids": "tw_1"}),
    ]
    for expected_call in expected:
        assert expected_call in audit_log.call_args_list


@pytest.mark.asyncio
async def test_catch_all_hides_raw_error_but_audit_keeps_it():
    repo = AsyncMock()
    repo.list_subjects.side_effect = OSError("disk full")
    tool = _tool_funcs()["list_subjects"]

    with (
        patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo),
        patch("src.mcp.tools.subject_tools.audit_log") as audit_log,
    ):
        result = _decode(await tool())

    assert result == {
        "success": False,
        "error": "list_subjects 查询失败，请稍后重试",
        "error_type": "internal",
    }
    assert "disk full" not in result["error"]
    audit_log.assert_called_once_with(
        "list_subjects",
        "read",
        params={"status": None},
        result="failure",
        error="disk full",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "kwargs", "expected_error"),
    [
        (
            "put_subject_digest",
            {
                "subject_id": "sub_test",
                "interval_start": "2026-07-01T00:00:00Z",
                "interval_end": "2026-07-02T00:00:00Z",
                "highlights": "{bad json",
            },
            "highlights 解析失败",
        ),
        (
            "put_subject_review",
            {
                "subject_id": "sub_test",
                "prev_version": 0,
                "sections": "{bad json",
                "covered_until": "2026-07-02T00:00:00Z",
            },
            "sections 解析失败",
        ),
        (
            "put_subject_review",
            {
                "subject_id": "sub_test",
                "prev_version": 0,
                "sections": [{"title": "现状", "body": "内容"}],
                "covered_until": "2026-07-02T00:00:00Z",
                "trend": "{bad json",
            },
            "trend 解析失败",
        ),
    ],
)
async def test_malformed_json_returns_curated_error(tool_name, kwargs, expected_error):
    tool = _tool_funcs()[tool_name]

    with patch("src.mcp.tools.subject_tools.require_scope", return_value=None):
        result = _decode(await tool(**kwargs))

    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert result["error"] == expected_error
    assert "Expecting property name" not in result["error"]
