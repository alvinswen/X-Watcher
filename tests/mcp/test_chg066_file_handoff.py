"""CHG-066 save_summaries 文件交接通道回归。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.mcp import handoff
from src.mcp.helpers import error_response
from src.mcp.tools import summarization_tools
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

_CREATED_AT = datetime.fromtimestamp(0, UTC)
_DATA_KEYS = {"saved", "failed", "total", "errors", "rejected"}


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    handoff.handoff_dir(tmp_path).mkdir()
    from src.mcp.server import create_mcp_server

    registered = create_mcp_server()._tool_manager._tools
    return {name: tool.fn for name, tool in registered.items()}


def _tweet(tweet_id: str, text: str = "中文测试推文") -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=text,
        author_username="alice",
        created_at=_CREATED_AT,
    )


async def _seed(root: Path, *tweets: Tweet) -> None:
    await FileTweetStore(root).save_tweets(list(tweets), early_stop_threshold=0)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(root: Path, name: str, data: bytes) -> tuple[Path, str]:
    target = handoff.handoff_dir(root) / name
    target.write_bytes(data)
    return target, _digest(data)


def _write_json(root: Path, name: str, value: Any) -> tuple[Path, str]:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return _write_bytes(root, name, data)


async def _call(
    tool: Any,
    *,
    summaries: Any = None,
    summaries_file: str | None = None,
    file_sha256: str | None = None,
) -> tuple[dict[str, Any], MagicMock]:
    with (
        patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
        patch("src.mcp.security.audit_log") as audit,
    ):
        raw = await tool(
            summaries=summaries,
            summaries_file=summaries_file,
            file_sha256=file_sha256,
        )
    return json.loads(raw), audit


async def _summary(root: Path, tweet_id: str) -> Any:
    return await FileSummaryStore(root).get_summary_by_tweet(tweet_id)


def _assert_batch(result: dict[str, Any], category: str) -> None:
    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert result["batch_category"] == category


@pytest.mark.asyncio
async def test_tc_mcp_369_double_or_missing_channels_are_rejected(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    target, digest = _write_json(tmp_path, "combo.json", [])
    both, both_audit = await _call(
        tools["save_summaries"],
        summaries=[],
        summaries_file=str(target),
        file_sha256=digest,
    )
    neither, neither_audit = await _call(tools["save_summaries"])

    for result, expected in (
        (both, summarization_tools._GUIDANCE_COMBO_BOTH),
        (neither, summarization_tools._GUIDANCE_COMBO_NEITHER),
    ):
        _assert_batch(result, handoff.BATCH_INVALID_PARAM_COMBO)
        assert result["error"] == expected
    for audit in (both_audit, neither_audit):
        assert audit.call_args.kwargs["result"] == "failure"
        assert audit.call_args.kwargs["params"]["batch_category"] == (
            handoff.BATCH_INVALID_PARAM_COMBO
        )
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_370_file_and_sha_must_be_paired(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    target, _ = _write_json(tmp_path, "paired.json", [])
    no_sha, _ = await _call(
        tools["save_summaries"], summaries_file=str(target)
    )
    no_file, _ = await _call(
        tools["save_summaries"], file_sha256="0" * 64
    )

    _assert_batch(no_sha, handoff.BATCH_INVALID_PARAM_COMBO)
    _assert_batch(no_file, handoff.BATCH_INVALID_PARAM_COMBO)
    assert no_sha["error"] == summarization_tools._GUIDANCE_COMBO_NO_SHA
    assert no_file["error"] == summarization_tools._GUIDANCE_COMBO_NO_FILE
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_371_outside_and_nested_paths_do_not_leak_root(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    data = b"[]"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_bytes(data)
    nested = handoff.handoff_dir(tmp_path) / "nested"
    nested.mkdir()
    child = nested / "child.json"
    child.write_bytes(data)
    try:
        results = [
            (await _call(
                tools["save_summaries"],
                summaries_file=str(path),
                file_sha256=_digest(data),
            ))[0]
            for path in (outside, child)
        ]
    finally:
        outside.unlink(missing_ok=True)

    for result in results:
        _assert_batch(result, handoff.BATCH_PATH_NOT_ALLOWED)
        assert str(tmp_path) not in result["error"]
        assert "工具说明书" in result["error"]
        assert "绝对路径" in result["error"]


@pytest.mark.asyncio
async def test_tc_mcp_372_extension_rejects_and_dotdot_normalizes(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("path-ok"))
    payload = [{"tweet_id": "path-ok", "summary": "路径归一成功"}]
    data = json.dumps(payload, ensure_ascii=False).encode()
    txt, digest = _write_bytes(tmp_path, "bad.txt", data)
    no_ext, _ = _write_bytes(tmp_path, "bad", data)
    valid, valid_digest = _write_bytes(tmp_path, "ok.json", data)

    for path in (txt, no_ext):
        result, _ = await _call(
            tools["save_summaries"],
            summaries_file=str(path),
            file_sha256=digest,
        )
        _assert_batch(result, handoff.BATCH_PATH_NOT_ALLOWED)
    dotdot = valid.parent / ".." / handoff.HANDOFF_DIR_NAME / valid.name
    accepted, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(dotdot),
        file_sha256=valid_digest,
    )
    assert accepted["data"]["saved"] == 1
    assert await _summary(tmp_path, "path-ok") is not None


@pytest.mark.asyncio
async def test_tc_mcp_373_file_symlinks_reject_but_directory_route_passes(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("symlink-ok"))
    payload = [{"tweet_id": "symlink-ok", "summary": "目录链接可达"}]
    data = json.dumps(payload, ensure_ascii=False).encode()
    outside_real = tmp_path.parent / f"{tmp_path.name}-real.json"
    outside_real.write_bytes(data)
    inside_link = handoff.handoff_dir(tmp_path) / "outside-link.json"
    inside_link.symlink_to(outside_real)
    good, digest = _write_bytes(tmp_path, "good.json", data)
    outside_file_link = tmp_path.parent / f"{tmp_path.name}-file-link.json"
    outside_file_link.symlink_to(good)
    outside_dir_link = tmp_path.parent / f"{tmp_path.name}-dir-link"
    outside_dir_link.symlink_to(handoff.handoff_dir(tmp_path), target_is_directory=True)
    try:
        for path in (inside_link, outside_file_link):
            rejected, _ = await _call(
                tools["save_summaries"],
                summaries_file=str(path),
                file_sha256=digest,
            )
            _assert_batch(rejected, handoff.BATCH_PATH_NOT_ALLOWED)
        accepted, _ = await _call(
            tools["save_summaries"],
            summaries_file=str(outside_dir_link / good.name),
            file_sha256=digest,
        )
    finally:
        outside_file_link.unlink(missing_ok=True)
        outside_dir_link.unlink(missing_ok=True)
        outside_real.unlink(missing_ok=True)

    assert accepted["data"]["saved"] == 1
    assert await _summary(tmp_path, "symlink-ok") is not None


@pytest.mark.asyncio
async def test_tc_mcp_374_hard_link_is_rejected(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-hard-source.json"
    data = b"[]"
    outside.write_bytes(data)
    linked = handoff.handoff_dir(tmp_path) / "hard.json"
    os.link(outside, linked)
    try:
        result, _ = await _call(
            tools["save_summaries"],
            summaries_file=str(linked),
            file_sha256=_digest(data),
        )
    finally:
        outside.unlink(missing_ok=True)

    _assert_batch(result, handoff.BATCH_PATH_NOT_ALLOWED)
    assert "硬链接/管道" in result["error"]
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_375_fifo_is_rejected_without_blocking(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    fifo = handoff.handoff_dir(tmp_path) / "pipe.json"
    os.mkfifo(fifo)
    result, _ = await asyncio.wait_for(
        _call(
            tools["save_summaries"],
            summaries_file=str(fifo),
            file_sha256="0" * 64,
        ),
        timeout=1,
    )
    _assert_batch(result, handoff.BATCH_PATH_NOT_ALLOWED)
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


def _padded_payload(tweet_id: str, size: int) -> bytes:
    prefix = (
        '[{"tweet_id":"' + tweet_id + '","summary":"边界",' + '"padding":"'
    ).encode()
    suffix = b'"}]'
    padding = size - len(prefix) - len(suffix)
    assert padding >= 0
    return prefix + (b"a" * padding) + suffix


@pytest.mark.asyncio
async def test_tc_mcp_376_ten_megabyte_boundary_changes_effect(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("limit-ok"))
    at_limit = _padded_payload("limit-ok", handoff.MAX_HANDOFF_BYTES)
    too_large = _padded_payload("limit-too-large", handoff.MAX_HANDOFF_BYTES + 1)
    accepted_path, accepted_sha = _write_bytes(tmp_path, "limit.json", at_limit)
    rejected_path, rejected_sha = _write_bytes(tmp_path, "large.json", too_large)

    accepted, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(accepted_path),
        file_sha256=accepted_sha,
    )
    rejected, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(rejected_path),
        file_sha256=rejected_sha,
    )

    assert accepted["data"]["saved"] == 1
    _assert_batch(rejected, handoff.BATCH_FILE_TOO_LARGE)
    assert "10,485,760" in rejected["error"]
    assert "拆成多个文件分批" in rejected["error"]
    assert "勿覆盖" not in rejected["error"]
    assert await _summary(tmp_path, "limit-ok") is not None


@pytest.mark.asyncio
async def test_tc_mcp_377_wrong_digest_is_fail_closed(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    target, digest = _write_json(
        tmp_path, "wrong-sha.json", [{"tweet_id": "missing", "summary": "不会写"}]
    )
    wrong = "0" * 64 if digest != "0" * 64 else "1" * 64
    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=wrong,
    )

    _assert_batch(result, handoff.BATCH_SHA256_MISMATCH)
    assert "以新文件名重写文件" in result["error"]
    assert "被拒文件保留作排查物证" in result["error"]
    assert target.exists()
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_378_digest_format_rejects_but_case_and_space_pass(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("sha-case"))
    target, digest = _write_json(
        tmp_path, "sha-case.json", [{"tweet_id": "sha-case", "summary": "摘要"}]
    )
    malformed, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest[:-1],
    )
    upper, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest.upper(),
    )
    spaced, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=f"  {digest.upper()}  ",
    )

    _assert_batch(malformed, handoff.BATCH_SHA256_MISMATCH)
    assert "64 位十六进制串" in malformed["error"]
    assert upper["data"]["saved"] == 1
    assert spaced["data"]["saved"] == 1


@pytest.mark.asyncio
async def test_tc_mcp_379_overwritten_file_rejects_stale_digest(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    first = b'[{"tweet_id":"a","summary":"A"}]'
    second = b'[{"tweet_id":"b","summary":"B"}]'
    target, first_sha = _write_bytes(tmp_path, "race.json", first)
    target.write_bytes(second)

    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=first_sha,
    )
    _assert_batch(result, handoff.BATCH_SHA256_MISMATCH)
    assert "并发写同名文件" in result["error"]
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_380_odd_unicode_escapes_report_count_offset_and_value(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    slash = chr(92)
    samples = [slash + "u0041", (slash * 3) + "u0041"]
    for index, escaped in enumerate(samples):
        text = '[{"tweet_id":"escape","summary":"' + escaped + '"}]'
        data = text.encode()
        target, digest = _write_bytes(tmp_path, f"escape-{index}.json", data)
        result, _ = await _call(
            tools["save_summaries"],
            summaries_file=str(target),
            file_sha256=digest,
        )
        _assert_batch(result, handoff.BATCH_ESCAPED_UNICODE_FOUND)
        assert "命中 1 处" in result["error"]
        assert "首处字符偏移" in result["error"]
        assert slash + "u0041" in result["error"]
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_381_even_escapes_and_chinese_round_trip(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    slash = chr(92)
    expected = [slash + "u0041", (slash * 2) + "u0041", "熬过中文直写"]
    ids = ["even-two", "even-four", "chinese"]
    await _seed(tmp_path, *(_tweet(tweet_id) for tweet_id in ids))

    for index, (tweet_id, summary) in enumerate(zip(ids, expected, strict=True)):
        target, digest = _write_json(
            tmp_path,
            f"even-{index}.json",
            [{"tweet_id": tweet_id, "summary": summary}],
        )
        result, _ = await _call(
            tools["save_summaries"],
            summaries_file=str(target),
            file_sha256=digest,
        )
        assert result["data"]["saved"] == 1
        assert (await _summary(tmp_path, tweet_id)).summary_text == summary


@pytest.mark.asyncio
async def test_tc_mcp_382_control_character_escape_is_rejected(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    slash = chr(92)
    data = json.dumps(
        [{"tweet_id": "control", "summary": "前" + chr(11) + "后"}],
        ensure_ascii=False,
    ).encode()
    assert (slash + "u000b").encode() in data
    target, digest = _write_bytes(tmp_path, "control.json", data)
    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    _assert_batch(result, handoff.BATCH_ESCAPED_UNICODE_FOUND)
    assert "请先清理控制字符" in result["error"]
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_383_short_escapes_match_parameter_channel(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    file_id = "short-file"
    param_id = "short-param"
    summary = "第一行\n第二行\t尾部"
    await _seed(tmp_path, _tweet(file_id), _tweet(param_id))
    target, digest = _write_json(
        tmp_path, "short.json", [{"tweet_id": file_id, "summary": summary}]
    )
    file_result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    param_result, _ = await _call(
        tools["save_summaries"],
        summaries=[{"tweet_id": param_id, "summary": summary}],
    )

    assert file_result["data"]["saved"] == 1
    assert param_result["data"]["saved"] == 1
    assert (await _summary(tmp_path, file_id)).summary_text == summary
    assert (await _summary(tmp_path, param_id)).summary_text == summary


@pytest.mark.asyncio
async def test_tc_mcp_384_invalid_json_variants_have_targeted_guidance(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    valid = json.dumps([{"tweet_id": "x", "summary": "中文"}], ensure_ascii=False)
    samples = [
        (b"\xef\xbb\xbf" + valid.encode(), "UTF-8 无 BOM"),
        (valid.encode("gbk"), "不是 UTF-8 编码"),
        (b'[{"tweet_id":', "不是合法 JSON"),
    ]
    for index, (data, phrase) in enumerate(samples):
        target, digest = _write_bytes(tmp_path, f"invalid-{index}.json", data)
        result, _ = await _call(
            tools["save_summaries"],
            summaries_file=str(target),
            file_sha256=digest,
        )
        _assert_batch(result, handoff.BATCH_INVALID_JSON)
        assert phrase in result["error"]
    assert await FileSummaryStore(tmp_path).get_all_summaries() == []


@pytest.mark.asyncio
async def test_tc_mcp_385_top_level_object_is_rejected(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    target, digest = _write_json(
        tmp_path, "object.json", {"tweet_id": "x", "summary": "摘要"}
    )
    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    _assert_batch(result, handoff.BATCH_NOT_AN_ARRAY)
    assert "顶层必须是数组" in result["error"]
    assert "与 summaries 参数同构" in result["error"]


@pytest.mark.asyncio
async def test_tc_mcp_386_empty_file_array_has_receipt(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    target, digest = _write_json(tmp_path, "empty.json", [])
    file_result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest.upper(),
    )
    param_result, _ = await _call(tools["save_summaries"], summaries=[])

    assert file_result["data"] == {
        "saved": 0,
        "failed": 0,
        "total": 0,
        "errors": [],
        "rejected": [],
        "file_receipt": {"file_sha256": digest, "item_count": 0},
    }
    assert param_result["data"] == {
        "saved": 0,
        "failed": 0,
        "total": 0,
        "errors": [],
        "rejected": [],
    }


@pytest.mark.asyncio
async def test_tc_mcp_387_missing_allowed_file_is_unreadable(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    missing = handoff.handoff_dir(tmp_path) / "ghost.json"
    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(missing),
        file_sha256="0" * 64,
    )
    _assert_batch(result, handoff.BATCH_FILE_UNREADABLE)
    assert "已用 Write 工具落盘" in result["error"]
    assert "逐字一致" in result["error"]


@pytest.mark.asyncio
async def test_tc_mcp_388_permission_guard_runs_before_file_loading(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("permission"))
    target, digest = _write_json(
        tmp_path,
        "permission.json",
        [{"tweet_id": "permission", "summary": "获准后写入"}],
    )
    denied = error_response("需要管理员权限", "permission")
    with (
        patch(
            "src.mcp.tools.summarization_tools.require_admin", return_value=denied
        ),
        patch.object(handoff, "load_handoff_file") as loader,
    ):
        blocked = json.loads(
            await tools["save_summaries"](
                summaries_file=str(target), file_sha256=digest
            )
        )
    loader.assert_not_called()
    assert blocked["error_type"] == "permission"
    assert "batch_category" not in blocked
    assert await _summary(tmp_path, "permission") is None

    accepted, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    assert accepted["data"]["saved"] == 1


@pytest.mark.asyncio
async def test_tc_mcp_389_parameter_channel_remains_compatible(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("param-list"), _tweet("param-json"))
    list_result, _ = await _call(
        tools["save_summaries"],
        summaries=[{"tweet_id": "param-list", "summary": "数组"}],
    )
    json_result, _ = await _call(
        tools["save_summaries"],
        summaries=json.dumps([{"tweet_id": "param-json", "summary": "字符串"}]),
    )
    invalid, _ = await _call(tools["save_summaries"], summaries={"bad": True})

    assert set(list_result["data"]) == _DATA_KEYS
    assert set(json_result["data"]) == _DATA_KEYS
    assert "file_receipt" not in list_result["data"]
    assert invalid["error"] == "summaries 必须是数组"
    assert "batch_category" not in invalid


@pytest.mark.asyncio
async def test_tc_mcp_390_parameter_file_parameter_has_no_state_leak(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    ids = ["channel-a", "channel-b", "channel-c"]
    await _seed(tmp_path, *(_tweet(tweet_id) for tweet_id in ids))
    first, first_audit = await _call(
        tools["save_summaries"],
        summaries=[{"tweet_id": ids[0], "summary": "A"}],
    )
    target, digest = _write_json(
        tmp_path, "channel-b.json", [{"tweet_id": ids[1], "summary": "B"}]
    )
    middle, middle_audit = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    last, last_audit = await _call(
        tools["save_summaries"],
        summaries=[{"tweet_id": ids[2], "summary": "C"}],
    )

    assert set(first["data"]) == set(last["data"]) == _DATA_KEYS
    assert "file_receipt" in middle["data"]
    assert "channel" not in first_audit.call_args.kwargs["params"]
    assert middle_audit.call_args.kwargs["params"]["channel"] == "file"
    assert "channel" not in last_audit.call_args.kwargs["params"]
    for tweet_id in ids:
        assert await _summary(tmp_path, tweet_id) is not None


def test_tc_mcp_393_docstring_contains_all_seven_contract_elements(
    tools: dict[str, Any]
) -> None:
    doc = inspect.getdoc(tools["save_summaries"])
    assert doc is not None
    phrases = (
        "已实证必然产生等长形近字转录漂移",
        "≥5 条或含中文正文",
        "文件通道操作序列（三步，顺序固定）",
        "原始字节整体计算 sha256",
        "UTF-8 无 BOM",
        "sse 跨机接入递不了",
        "本地文件",
        "分类枚举（8 值）",
        "服务端数据根",
        "直下的 handoff/ 子目录",
        "绝对路径",
        "被拒后重提必须换新文件名",
        "transcription_error",
        "not_found",
        "verification_failed",
    )
    assert all(phrase in doc for phrase in phrases)


def test_tc_mcp_395_categories_and_guidance_are_frozen_and_clean() -> None:
    categories = (
        handoff.BATCH_INVALID_PARAM_COMBO,
        handoff.BATCH_PATH_NOT_ALLOWED,
        handoff.BATCH_FILE_UNREADABLE,
        handoff.BATCH_FILE_TOO_LARGE,
        handoff.BATCH_SHA256_MISMATCH,
        handoff.BATCH_ESCAPED_UNICODE_FOUND,
        handoff.BATCH_INVALID_JSON,
        handoff.BATCH_NOT_AN_ARRAY,
    )
    assert categories == (
        "invalid_param_combo",
        "path_not_allowed",
        "file_unreadable",
        "file_too_large",
        "sha256_mismatch",
        "escaped_unicode_found",
        "invalid_json",
        "not_an_array",
    )
    guidance = (
        handoff.GUIDANCE_PATH_NOT_ALLOWED,
        handoff.GUIDANCE_FILE_UNREADABLE,
        handoff.GUIDANCE_FILE_TOO_LARGE,
        handoff.GUIDANCE_SHA256_MISMATCH,
        handoff.GUIDANCE_SHA256_FORMAT,
        handoff.GUIDANCE_ESCAPED_TEMPLATE,
        handoff.GUIDANCE_JSON_BOM,
        handoff.GUIDANCE_JSON_NOT_UTF8,
        handoff.GUIDANCE_JSON_SYNTAX,
    )
    expected = (
        "提交的文件路径不在白名单：只接受交接目录直下的 .json 常规文件（不收子目录、不跟符号链接、不收其他扩展名；非常规文件——硬链接/管道等——不收）。交接目录定位见工具说明书（服务端数据根直下的 handoff/ 子目录）；请把文件写到该目录直下、.json 扩展名、传绝对路径后重提。",
        "交接文件不存在或读取失败：请确认已用 Write 工具落盘、调用传入的路径与写入路径逐字一致后重提。",
        "交接文件超过 10MB 上限（10,485,760 字节）：请拆成多个文件分批调用；内容无需重新生成。",
        "提交的指纹与服务端对文件原始字节重算值不符：文件可能在算指纹后被改动或覆盖（并发写同名文件会表现为此拒绝），或指纹算错对象（须对文件原始字节整体计算，非文本、非逐条）。请以新文件名重写文件（勿覆盖原文件——被拒文件保留作排查物证）、重算指纹后重提；内容无需重新生成。",
        "指纹须为 64 位十六进制串（对交接文件原始字节整体计算的 sha256，大小写不敏感）。请重算指纹后重提；文件与内容无需改动。",
        "交接文件含真转义序列（单个反斜杠+u+4 位十六进制，命中 {count} 处，首处字符偏移 {offset}：{seq}）：该转义路径已实证必然产生等长形近字转录漂移。请用 UTF-8 直写方式重新序列化（非 ASCII 一律原样字符）为新文件后重提（勿覆盖原文件——被拒文件保留作排查物证）；若因正文含控制字符被强制转义，请先清理控制字符。双反斜杠字面文本与换行/制表等短转义不受影响；内容无需重新生成。",
        "交接文件带 UTF-8 BOM：请以 UTF-8 无 BOM 重新序列化写入新文件后重提（勿覆盖原文件——被拒文件保留作排查物证）；内容无需重新生成。",
        "交接文件不是 UTF-8 编码：请转为 UTF-8（无 BOM）写入新文件后重提（勿覆盖原文件）；内容无需重新生成。",
        "交接文件不是合法 JSON：请重新序列化为规范 JSON（UTF-8 无 BOM）写入新文件后重提（勿覆盖原文件——被拒文件保留作排查物证）；内容无需重新生成。",
    )
    assert guidance == expected
    assert all("summaries_file" not in text for text in guidance)
    assert all("file_sha256" not in text for text in guidance)
    assert all(not any(ord(char) < 32 for char in text) for text in guidance)


@pytest.mark.asyncio
async def test_tc_mcp_396_audit_has_file_fields_without_response_leak(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    await _seed(tmp_path, _tweet("audit-ok"))
    target, digest = _write_json(
        tmp_path, "audit.json", [{"tweet_id": "audit-ok", "summary": "审计"}]
    )
    accepted, success_audit = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest.upper(),
    )
    outside = tmp_path.parent / f"{tmp_path.name}-audit-outside.json"
    outside.write_bytes(b"[]")
    try:
        rejected, failure_audit = await _call(
            tools["save_summaries"],
            summaries_file=str(outside),
            file_sha256=_digest(b"[]"),
        )
    finally:
        outside.unlink(missing_ok=True)

    success_params = success_audit.call_args.kwargs["params"]
    assert success_params["channel"] == "file"
    assert success_params["summaries_file"] == str(target)
    assert success_params["file_sha256"] == digest
    failure_params = failure_audit.call_args.kwargs["params"]
    assert failure_params["batch_category"] == handoff.BATCH_PATH_NOT_ALLOWED
    assert failure_params["summaries_file"] == str(outside)
    assert failure_audit.call_args.kwargs["result"] == "failure"
    assert str(outside) not in rejected["error"]
    assert accepted["success"] is True


def test_tc_mcp_397_locked_terms_have_expected_footprint() -> None:
    root = Path(__file__).parents[2]
    summary_source = (root / "src/mcp/tools/summarization_tools.py").read_text()
    assert summary_source.count("tweet_id}:claude_code") == 1

    candidates = [
        *root.joinpath("src/mcp").rglob("*.py"),
        *root.joinpath("tests/mcp").rglob("*.py"),
        *root.joinpath("tests/mcp").rglob("*.json"),
    ]
    summaries_file_hits = {
        path.relative_to(root)
        for path in candidates
        if re.search(r"\bsummaries_file\b", path.read_text())
    }
    handoff_hits = {
        path.relative_to(root)
        for path in candidates
        if re.search(r"\bhandoff\b", path.read_text())
    }
    assert len(summaries_file_hits) == 4
    assert len(handoff_hits) == 5

    fallback_sources = [summary_source]
    fallback_sources.extend(
        path.read_text() for path in root.joinpath("src/summarization").rglob("*.py")
    )
    assert not re.search(
        r"_DATA\b|MOCK_|FALLBACK_|DEFAULT_", "\n".join(fallback_sources)
    )


@pytest.mark.asyncio
async def test_tc_mcp_399_file_channel_keeps_item_level_categories(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    valid_id = "file-valid"
    await _seed(tmp_path, _tweet(valid_id))
    payload = [
        {"tweet_id": valid_id, "summary": "合法"},
        {"tweet_id": "9876543210987654321", "summary": "不存在"},
        {"tweet_id": 123, "summary": "类型错误"},
    ]
    target, digest = _write_json(tmp_path, "mixed.json", payload)
    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )

    assert result["success"] is True
    assert result["data"]["saved"] == 1
    assert result["data"]["file_receipt"]["item_count"] == 3
    assert {item["category"] for item in result["data"]["rejected"]} == {
        "not_found",
        "transcription_error",
    }
    assert await _summary(tmp_path, valid_id) is not None
    assert await _summary(tmp_path, "9876543210987654321") is None


@pytest.mark.asyncio
async def test_tc_scn_116_file_round_trip_preserves_high_risk_text(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    tweet_id = "round-trip"
    slash = chr(92)
    summary = "终于熬过关键阶段"
    translation = "字面转义示例：" + slash + "u0041"
    await _seed(
        tmp_path,
        _tweet(tweet_id, "This English source text needs a faithful translation."),
    )
    with patch(
        "src.mcp.tools.summarization_tools.require_admin", return_value=None
    ):
        before = json.loads(await tools["get_unsummarized_tweets"]())
    assert [item["tweet_id"] for item in before["data"]["tweets"]] == [tweet_id]

    target, digest = _write_json(
        tmp_path,
        "round-trip.json",
        [{"tweet_id": tweet_id, "summary": summary, "translation": translation}],
    )
    result, _ = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    stored = await _summary(tmp_path, tweet_id)
    with patch(
        "src.mcp.tools.summarization_tools.require_admin", return_value=None
    ):
        after = json.loads(await tools["get_unsummarized_tweets"]())

    assert result["data"]["file_receipt"] == {
        "file_sha256": digest,
        "item_count": 1,
    }
    assert stored.summary_text == summary
    assert stored.translation_text == translation
    assert after["data"]["tweets"] == []
    assert target.exists()


@pytest.mark.asyncio
async def test_tc_scn_117_rejected_file_leaves_read_side_unchanged(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    tweet_id = "rejected-round-trip"
    slash = chr(92)
    await _seed(tmp_path, _tweet(tweet_id))
    with patch(
        "src.mcp.tools.summarization_tools.require_admin", return_value=None
    ):
        before = json.loads(await tools["get_unsummarized_tweets"]())
    text = (
        '[{"tweet_id":"'
        + tweet_id
        + '","summary":"'
        + slash
        + 'u0041"}]'
    )
    target, digest = _write_bytes(tmp_path, "rejected.json", text.encode())
    result, audit = await _call(
        tools["save_summaries"],
        summaries_file=str(target),
        file_sha256=digest,
    )
    with patch(
        "src.mcp.tools.summarization_tools.require_admin", return_value=None
    ):
        after = json.loads(await tools["get_unsummarized_tweets"]())

    _assert_batch(result, handoff.BATCH_ESCAPED_UNICODE_FOUND)
    assert await _summary(tmp_path, tweet_id) is None
    assert before["data"]["tweets"] == after["data"]["tweets"]
    assert target.exists()
    assert audit.call_args.kwargs["result"] == "failure"
    assert audit.call_args.kwargs["params"]["batch_category"] == (
        handoff.BATCH_ESCAPED_UNICODE_FOUND
    )
