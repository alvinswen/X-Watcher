"""CHG-046 save_summaries tweet_id 边界防御回归。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.mcp.helpers import error_response
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

_CREATED_AT = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
_TRANSCRIPTION_REASON = (
    "疑似转写错误，请从 get_unsummarized_tweets 返回原样复制 tweet_id（字符串，勿手工拼装或改类型）"
)
_NOT_FOUND_REASON = "该推文不在推文库中，疑似虚构，请勿手工构造 tweet_id；如确信应存在请先抓取入库"


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.mcp.server import create_mcp_server

    registered = create_mcp_server()._tool_manager._tools
    return {name: tool.fn for name, tool in registered.items()}


async def _seed(root: Path, *tweets: Tweet) -> None:
    await FileTweetStore(root).save_tweets(
        list(tweets),
        early_stop_threshold=0,
    )


def _tweet(tweet_id: str, text: str = "测试推文") -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=text,
        author_username="alice",
        created_at=_CREATED_AT,
    )


async def _save(save_summaries, summaries):
    with (
        patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
        patch("src.mcp.security.audit_log") as audit,
    ):
        result = json.loads(await save_summaries(summaries=summaries))
    return result, audit


def _audit_params(audit: MagicMock) -> dict[str, int]:
    audit.assert_called_once()
    return audit.call_args.kwargs["params"]


@pytest.mark.asyncio
async def test_existing_and_newly_seeded_ids_save_and_round_trip(
    tools,
    tmp_path: Path,
) -> None:
    """TC-MCP-265/266: 正常与刚入库 ID 均立即放行并可读回。"""
    save_summaries = tools["save_summaries"]
    get_unsummarized = tools["get_unsummarized_tweets"]
    first_id = "2073194663793797837"
    fresh_id = "2073194663793797838"

    await _seed(tmp_path, _tweet(first_id))
    first, first_audit = await _save(
        save_summaries,
        [{"tweet_id": first_id, "summary": "摘要 A"}],
    )
    await _seed(tmp_path, _tweet(fresh_id))
    fresh, fresh_audit = await _save(
        save_summaries,
        [{"tweet_id": fresh_id, "summary": "摘要 B"}],
    )

    assert first["data"] == {
        "saved": 1,
        "failed": 0,
        "total": 1,
        "errors": [],
        "rejected": [],
    }
    assert fresh["data"] == {
        "saved": 1,
        "failed": 0,
        "total": 1,
        "errors": [],
        "rejected": [],
    }
    for audit in (first_audit, fresh_audit):
        assert _audit_params(audit) == {
            "total": 1,
            "saved": 1,
            "failed": 0,
            "rejected_transcription_error": 0,
            "rejected_not_found": 0,
            "rejected_verification_failed": 0,
        }

    store = FileSummaryStore(tmp_path)
    assert (await store.get_summary_by_tweet(first_id)).summary_text == "摘要 A"
    assert (await store.get_summary_by_tweet(fresh_id)).summary_text == "摘要 B"
    with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
        remaining = json.loads(await get_unsummarized(limit=10))
    assert remaining["data"]["tweets"] == []


@pytest.mark.asyncio
async def test_missing_ids_are_classified_by_ascii_shape(tools) -> None:
    """TC-MCP-267/268/271/272/274: 格式只分文案，存在性决定放行。"""
    cases = [
        ("2073194663察793797837", "transcription_error"),
        ("9876543210987654321", "not_found"),
        ("１２３４５６７８９０１２３４５６７８９", "transcription_error"),
        ("12345678901234", "transcription_error"),
        ("123456789012345", "not_found"),
        ("12345678901234567890", "not_found"),
        ("123456789012345678901", "transcription_error"),
        (" 9876543210987654321 ", "transcription_error"),
    ]

    result, audit = await _save(
        tools["save_summaries"],
        [{"tweet_id": tweet_id, "summary": "摘要"} for tweet_id, _ in cases],
    )

    assert result["data"]["saved"] == 0
    assert result["data"]["failed"] == len(cases)
    assert [(item["tweet_id"], item["category"]) for item in result["data"]["rejected"]] == cases
    reasons = {item["category"]: item["reason"] for item in result["data"]["rejected"]}
    assert reasons["transcription_error"] == _TRANSCRIPTION_REASON
    assert reasons["not_found"] == _NOT_FOUND_REASON
    assert _audit_params(audit)["rejected_transcription_error"] == 5
    assert _audit_params(audit)["rejected_not_found"] == 3


@pytest.mark.asyncio
async def test_existing_out_of_shape_id_is_not_misclassified(
    tools,
    tmp_path: Path,
) -> None:
    """TC-MCP-273: 库内真实存在的 14 位 ID 不因格式带被误杀。"""
    tweet_id = "12345678901234"
    await _seed(tmp_path, _tweet(tweet_id))

    result, _ = await _save(
        tools["save_summaries"],
        [{"tweet_id": tweet_id, "summary": "真实短 ID 摘要"}],
    )

    assert result["data"]["saved"] == 1
    assert result["data"]["rejected"] == []


@pytest.mark.asyncio
async def test_non_string_ids_are_rejected_without_normalization(tools) -> None:
    """TC-MCP-269/270: 数字与 unhashable 字典原值回显且批次不崩。"""
    submitted = [123, {"x": 1}]

    result, audit = await _save(
        tools["save_summaries"],
        [{"tweet_id": tweet_id, "summary": "摘要"} for tweet_id in submitted],
    )

    assert result["data"]["saved"] == 0
    assert result["data"]["failed"] == 2
    assert [item["tweet_id"] for item in result["data"]["rejected"]] == submitted
    assert {item["category"] for item in result["data"]["rejected"]} == {"transcription_error"}
    assert "tweet_id=123" in result["data"]["errors"][0]
    assert "tweet_id={'x': 1}" in result["data"]["errors"][1]
    assert _audit_params(audit)["rejected_transcription_error"] == 2


@pytest.mark.asyncio
async def test_missing_required_and_non_object_items_stay_errors_only(tools) -> None:
    """TC-MCP-274/275: 必填闸与非对象条目不污染 rejected。"""
    result, audit = await _save(
        tools["save_summaries"],
        [
            "not-an-object",
            {"tweet_id": "", "summary": "摘要"},
            {"summary": "缺 ID"},
            {"tweet_id": "123456789012345"},
        ],
    )

    assert result["data"]["saved"] == 0
    assert result["data"]["failed"] == 4
    assert result["data"]["rejected"] == []
    assert len(result["data"]["errors"]) == 4
    assert _audit_params(audit)["rejected_transcription_error"] == 0
    assert _audit_params(audit)["rejected_not_found"] == 0


@pytest.mark.asyncio
async def test_empty_list_is_success_and_audits_all_zeroes(tools) -> None:
    """TC-MCP-276: 空批安全返回，审计三类键恒在。"""
    result, audit = await _save(tools["save_summaries"], [])

    assert result == {
        "success": True,
        "data": {
            "saved": 0,
            "failed": 0,
            "total": 0,
            "errors": [],
            "rejected": [],
        },
    }
    assert _audit_params(audit) == {
        "total": 0,
        "saved": 0,
        "failed": 0,
        "rejected_transcription_error": 0,
        "rejected_not_found": 0,
        "rejected_verification_failed": 0,
    }


@pytest.mark.asyncio
async def test_invalid_overall_input_remains_validation_error(tools) -> None:
    """TC-MCP-277: 顶层形态错误仍使用 error_type=validation。"""
    save_summaries = tools["save_summaries"]
    with (
        patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
        patch("src.mcp.security.audit_log") as audit,
    ):
        invalid_json = json.loads(await save_summaries(summaries="not-json"))
        not_array = json.loads(await save_summaries(summaries=123))

    for result in (invalid_json, not_array):
        assert result["success"] is False
        assert result["error_type"] == "validation"
        assert "data" not in result
    audit.assert_not_called()


@pytest.mark.asyncio
async def test_permission_guard_precedes_boundary_processing(tools) -> None:
    """TC-MCP-278: 非管理员仍在边界逻辑之前被拒。"""
    denied = error_response("需要管理员权限", "permission")
    with patch(
        "src.mcp.tools.summarization_tools.require_admin",
        return_value=denied,
    ):
        result = json.loads(
            await tools["save_summaries"](
                summaries=[{"tweet_id": "123456789012345", "summary": "摘要"}]
            )
        )

    assert result == {
        "success": False,
        "error": "需要管理员权限",
        "error_type": "permission",
    }


@pytest.mark.asyncio
async def test_mixed_batch_partially_succeeds_with_all_categories(
    tools,
    tmp_path: Path,
) -> None:
    """TC-MCP-279: 合法项与三类非法项互不连坐。"""
    valid_id = "2073194663793797837"
    english_id = "2073194663793797838"
    await _seed(
        tmp_path,
        _tweet(valid_id),
        _tweet(
            english_id,
            "This sufficiently long English tweet requires a complete translation.",
        ),
    )

    result, audit = await _save(
        tools["save_summaries"],
        [
            {"tweet_id": valid_id, "summary": "合法摘要"},
            {"tweet_id": 123, "summary": "类型错误"},
            {"tweet_id": "9876543210987654321", "summary": "不存在"},
            {"tweet_id": english_id, "summary": "缺少译文"},
        ],
    )

    assert result["data"]["saved"] == 1
    assert result["data"]["failed"] == 3
    assert [item["category"] for item in result["data"]["rejected"]] == [
        "transcription_error",
        "not_found",
        "verification_failed",
    ]
    assert result["data"]["rejected"][2]["reason"] == "英文推文缺少翻译"
    assert _audit_params(audit) == {
        "total": 4,
        "saved": 1,
        "failed": 3,
        "rejected_transcription_error": 1,
        "rejected_not_found": 1,
        "rejected_verification_failed": 1,
    }
    assert await FileSummaryStore(tmp_path).get_summary_by_tweet(valid_id) is not None
    assert await FileSummaryStore(tmp_path).get_summary_by_tweet(english_id) is None


@pytest.mark.asyncio
async def test_large_rejected_batch_is_complete_while_errors_are_truncated(
    tools,
) -> None:
    """TC-MCP-280: rejected 保留 12 条，errors 只保留前 10 条。"""
    not_found = [f"98765432109876543{i:02d}" for i in range(7)]
    transcription = [f"bad-id-{i}" for i in range(5)]
    submitted = not_found + transcription

    result, audit = await _save(
        tools["save_summaries"],
        [{"tweet_id": tweet_id, "summary": "摘要"} for tweet_id in submitted],
    )

    assert result["data"]["saved"] == 0
    assert result["data"]["failed"] == 12
    assert len(result["data"]["rejected"]) == 12
    assert len(result["data"]["errors"]) == 10
    assert [item["tweet_id"] for item in result["data"]["rejected"]] == submitted
    assert _audit_params(audit)["rejected_not_found"] == 7
    assert _audit_params(audit)["rejected_transcription_error"] == 5
    assert _audit_params(audit)["rejected_verification_failed"] == 0


@pytest.mark.asyncio
async def test_verification_failure_and_pure_media_release_are_preserved(
    tools,
    tmp_path: Path,
) -> None:
    """TC-SUMM-100/101: 缺译拒绝，真实纯媒体空文仍放行。"""
    english_id = "2073194663793797837"
    media_id = "2073194663793797838"
    await _seed(
        tmp_path,
        _tweet(
            english_id,
            "This sufficiently long English tweet requires a complete translation.",
        ),
        _tweet(media_id, ""),
    )

    result, audit = await _save(
        tools["save_summaries"],
        [
            {"tweet_id": english_id, "summary": "英文摘要"},
            {"tweet_id": media_id, "summary": "图片推文摘要"},
        ],
    )

    assert result["data"]["saved"] == 1
    assert result["data"]["failed"] == 1
    assert result["data"]["rejected"] == [
        {
            "tweet_id": english_id,
            "category": "verification_failed",
            "reason": "英文推文缺少翻译",
        }
    ]
    assert _audit_params(audit)["rejected_verification_failed"] == 1
    store = FileSummaryStore(tmp_path)
    assert await store.get_summary_by_tweet(english_id) is None
    assert (await store.get_summary_by_tweet(media_id)).summary_text == "图片推文摘要"


@pytest.mark.asyncio
async def test_rejected_ids_leave_read_paths_unchanged(
    tools,
    tmp_path: Path,
) -> None:
    """TC-SCN-082: 被拒幻觉 ID 不落盘且不改变待译队列。"""
    real_id = "2073194663793797837"
    await _seed(tmp_path, _tweet(real_id))
    get_unsummarized = tools["get_unsummarized_tweets"]
    with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
        before = json.loads(await get_unsummarized(limit=10))["data"]["tweets"]

    result, _ = await _save(
        tools["save_summaries"],
        [
            {"tweet_id": "9876543210987654321", "summary": "幻觉摘要"},
            {"tweet_id": "bad-id", "summary": "错抄摘要"},
        ],
    )

    with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
        after = json.loads(await get_unsummarized(limit=10))["data"]["tweets"]
    store = FileSummaryStore(tmp_path)
    assert result["data"]["saved"] == 0
    assert before == after
    assert await store.get_summary_by_tweet("9876543210987654321") is None
    assert await store.get_summary_by_tweet("bad-id") is None
    assert await store.get_all_summaries() == []


@pytest.mark.asyncio
async def test_duplicate_id_keeps_existing_upsert_behavior(
    tools,
    tmp_path: Path,
) -> None:
    """TC-MCP-289: 同批重复 ID 仍由仓储就地更新并保持幂等。"""
    tweet_id = "2073194663793797837"
    await _seed(tmp_path, _tweet(tweet_id))
    batch = [
        {"tweet_id": tweet_id, "summary": "第一版"},
        {"tweet_id": tweet_id, "summary": "第二版"},
    ]

    first, _ = await _save(tools["save_summaries"], batch)
    second, _ = await _save(tools["save_summaries"], batch)

    records = await FileSummaryStore(tmp_path).get_all_summaries()
    assert first["data"]["saved"] == 2
    assert second["data"]["saved"] == 2
    assert len(records) == 1
    assert records[0].summary_text == "第二版"


@pytest.mark.asyncio
async def test_copy_mistype_classify_and_retry_flow(
    tools,
    tmp_path: Path,
) -> None:
    """TC-SCN-081: 取数、错抄、分类、原样重提形成自愈闭环。"""
    correct_id = "2073194663793797837"
    mistyped_id = "2073194663793797836"
    await _seed(tmp_path, _tweet(correct_id))
    get_unsummarized = tools["get_unsummarized_tweets"]

    with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
        fetched = json.loads(await get_unsummarized(limit=10))
    assert fetched["data"]["tweets"][0]["tweet_id"] == correct_id

    wrong, _ = await _save(
        tools["save_summaries"],
        [{"tweet_id": mistyped_id, "summary": "错抄摘要"}],
    )
    assert wrong["data"]["rejected"][0]["category"] == "not_found"

    retried, _ = await _save(
        tools["save_summaries"],
        [{"tweet_id": correct_id, "summary": "正确摘要"}],
    )
    assert retried["data"]["saved"] == 1
    with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
        remaining = json.loads(await get_unsummarized(limit=10))
    assert remaining["data"]["tweets"] == []
