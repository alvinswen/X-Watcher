"""CHG-067 subject writeback 文件交接通道回归。"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.mcp import handoff
from src.mcp.helpers import error_response
from src.mcp.tools import subject_tools
from src.subjects.models import SubjectMatch
from src.subjects.provenance import build_candidate_set_hash
from src.subjects.store import FileSubjectStore

_BASE = datetime.fromtimestamp(0, UTC)
_END = _BASE + timedelta(hours=1)
_PROMPT_HASH = "b" * 64


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    handoff.handoff_dir(tmp_path).mkdir()
    from src.mcp.server import create_mcp_server

    registered = create_mcp_server()._tool_manager._tools
    return {name: tool.fn for name, tool in registered.items()}


async def _subject(root: Path, *tweet_ids: str) -> tuple[FileSubjectStore, str]:
    repo = FileSubjectStore(root)
    subject = await repo.create_subject(
        name="CHG-067 测试议题",
        nl_description="验证 subject writeback 文件交接通道",
    )
    if tweet_ids:
        await repo.upsert_matches(
            [
                SubjectMatch(
                    subject_id=subject.subject_id,
                    tweet_id=tweet_id,
                    matched_at=_BASE + timedelta(minutes=index),
                )
                for index, tweet_id in enumerate(tweet_ids)
            ]
        )
    return repo, subject.subject_id


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(root: Path, name: str, data: bytes) -> tuple[Path, str]:
    target = handoff.handoff_dir(root) / name
    target.write_bytes(data)
    return target, _digest(data)


def _write_json(root: Path, name: str, value: Any) -> tuple[Path, str]:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return _write_bytes(root, name, data)


def _review_payload(body: str = "综述正文") -> dict[str, Any]:
    return {
        "sections": [
            {"title": "总览", "body": body, "cited_tweet_ids": []},
        ]
    }


def _digest_payload(text: str = "滚动新闻正文") -> dict[str, Any]:
    return {"digest_text": text, "highlights": [], "cited": []}


async def _invoke(
    tool: Any,
    *,
    denied: str | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], MagicMock]:
    with (
        patch("src.mcp.tools.subject_tools.require_scope", return_value=denied),
        patch("src.mcp.tools.subject_tools.audit_log") as audit,
    ):
        raw = await tool(**kwargs)
    return json.loads(raw), audit


async def _review(
    tools: dict[str, Any],
    subject_id: str,
    *,
    prev_version: int = 0,
    **kwargs: Any,
) -> tuple[dict[str, Any], MagicMock]:
    return await _invoke(
        tools["put_subject_review"],
        subject_id=subject_id,
        prev_version=prev_version,
        covered_until=_END.isoformat(),
        **kwargs,
    )


async def _put_digest(
    tools: dict[str, Any],
    subject_id: str,
    **kwargs: Any,
) -> tuple[dict[str, Any], MagicMock]:
    return await _invoke(
        tools["put_subject_digest"],
        subject_id=subject_id,
        interval_start=_BASE.isoformat(),
        interval_end=_END.isoformat(),
        **kwargs,
    )


def _assert_batch(result: dict[str, Any], category: str) -> None:
    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert result["batch_category"] == category
    assert "file_receipt" not in result


@pytest.mark.asyncio
async def test_tc_mcp_400_review_combo_variants_are_fail_closed(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path)
    target, sha256 = _write_json(tmp_path, "review_combo.json", _review_payload())
    calls = (
        (
            {"review_file": str(target), "file_sha256": sha256, "sections": []},
            subject_tools._GUIDANCE_REVIEW_COMBO_BOTH,
        ),
        ({"review_file": str(target)}, subject_tools._GUIDANCE_REVIEW_COMBO_NO_SHA),
        ({"file_sha256": sha256}, subject_tools._GUIDANCE_REVIEW_COMBO_NO_FILE),
        ({}, subject_tools._GUIDANCE_REVIEW_COMBO_NEITHER),
    )

    for kwargs, guidance in calls:
        result, audit = await _review(tools, subject_id, **kwargs)
        _assert_batch(result, handoff.BATCH_INVALID_PARAM_COMBO)
        assert result["error"] == guidance
        assert audit.call_args.kwargs["error"] == handoff.BATCH_INVALID_PARAM_COMBO
    assert await repo.get_review(subject_id) is None


@pytest.mark.asyncio
async def test_tc_mcp_401_digest_combo_and_missing_body_are_distinct(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path)
    target, sha256 = _write_json(tmp_path, "digest_combo.json", _digest_payload())
    calls = (
        (
            {"digest_file": str(target), "file_sha256": sha256, "digest_text": "双给"},
            subject_tools._GUIDANCE_DIGEST_COMBO_BOTH,
        ),
        ({"digest_file": str(target)}, subject_tools._GUIDANCE_DIGEST_COMBO_NO_SHA),
        ({"file_sha256": sha256}, subject_tools._GUIDANCE_DIGEST_COMBO_NO_FILE),
    )

    for kwargs, guidance in calls:
        result, _ = await _put_digest(tools, subject_id, **kwargs)
        _assert_batch(result, handoff.BATCH_INVALID_PARAM_COMBO)
        assert result["error"] == guidance
    missing, _ = await _put_digest(tools, subject_id)
    assert missing["error_type"] == "validation"
    assert missing["error"] == "digest_text 不能为空"
    assert "batch_category" not in missing
    assert await repo.list_digests(subject_id) == []


@pytest.mark.asyncio
async def test_tc_mcp_402_403_path_and_unreadable_gates_are_shared(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    raw = json.dumps(_review_payload(), ensure_ascii=False).encode()
    outside = tmp_path / "outside.json"
    outside.write_bytes(raw)
    nested = handoff.handoff_dir(tmp_path) / "nested"
    nested.mkdir()
    nested_file = nested / "nested.json"
    nested_file.write_bytes(raw)
    bad_ext = handoff.handoff_dir(tmp_path) / "bad.txt"
    bad_ext.write_bytes(raw)
    symlink = handoff.handoff_dir(tmp_path) / "link.json"
    symlink.symlink_to(outside)
    hardlink = handoff.handoff_dir(tmp_path) / "hard.json"
    os.link(outside, hardlink)
    fifo = handoff.handoff_dir(tmp_path) / "pipe.json"
    os.mkfifo(fifo)

    for path in (outside, nested_file, bad_ext, symlink, hardlink, fifo):
        review, _ = await _review(
            tools,
            subject_id,
            review_file=str(path),
            file_sha256=_digest(raw),
        )
        digest, _ = await _put_digest(
            tools,
            subject_id,
            digest_file=str(path),
            file_sha256=_digest(raw),
        )
        for result in (review, digest):
            _assert_batch(result, handoff.BATCH_PATH_NOT_ALLOWED)
            assert str(tmp_path) not in result["error"]

    ghost = handoff.handoff_dir(tmp_path) / "ghost.json"
    for result in (
        (await _review(tools, subject_id, review_file=str(ghost), file_sha256="0" * 64))[0],
        (await _put_digest(tools, subject_id, digest_file=str(ghost), file_sha256="0" * 64))[0],
    ):
        _assert_batch(result, handoff.BATCH_FILE_UNREADABLE)
        assert result["error"] == handoff.GUIDANCE_FILE_UNREADABLE

    review_ok_path, review_ok_sha = _write_json(
        tmp_path, "normalized_review.json", _review_payload("归一放行")
    )
    review_dotdot = review_ok_path.parent / ".." / "handoff" / review_ok_path.name
    review_ok, _ = await _review(
        tools,
        subject_id,
        review_file=str(review_dotdot),
        file_sha256=review_ok_sha,
    )
    assert review_ok["success"] is True
    digest_ok_path, digest_ok_sha = _write_json(
        tmp_path, "normalized_digest.json", _digest_payload("归一放行")
    )
    digest_dotdot = digest_ok_path.parent / ".." / "handoff" / digest_ok_path.name
    digest_ok, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_dotdot),
        file_sha256=digest_ok_sha,
    )
    assert digest_ok["success"] is True


@pytest.mark.asyncio
async def test_tc_mcp_404_ten_megabyte_boundary_changes_terminal_effect(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path)
    payload = {
        "digest_text": "边界正文",
        "highlights": [{"point": "", "cited_tweet_ids": []}],
    }
    empty = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    payload["highlights"][0]["point"] = "x" * (handoff.MAX_HANDOFF_BYTES - len(empty))
    exact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(exact) == handoff.MAX_HANDOFF_BYTES
    exact_path, exact_sha = _write_bytes(tmp_path, "exact.json", exact)
    accepted, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(exact_path),
        file_sha256=exact_sha,
    )
    assert accepted["success"] is True
    assert accepted["data"]["file_receipt"]["item_count"] == 1

    too_large_path, too_large_sha = _write_bytes(tmp_path, "too_large.json", exact + b" ")
    rejected, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(too_large_path),
        file_sha256=too_large_sha,
    )
    _assert_batch(rejected, handoff.BATCH_FILE_TOO_LARGE)
    assert len(await repo.list_digests(subject_id)) == 1


@pytest.mark.asyncio
async def test_tc_mcp_405_416_fingerprint_and_audit_preserve_distinct_forms(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    target, sha256 = _write_json(tmp_path, "uppercase.json", _review_payload())
    submitted = sha256.upper()
    accepted, audit = await _review(
        tools,
        subject_id,
        review_file=str(target),
        file_sha256=submitted,
    )
    assert accepted["success"] is True
    assert audit.call_args.kwargs["params"]["file_sha256"] == submitted
    assert accepted["data"]["file_receipt"]["file_sha256"] == sha256

    digest_target, digest_sha = _write_json(tmp_path, "digest_sha.json", _digest_payload())
    digest_submitted = digest_sha.upper()
    digest_accepted, digest_audit = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_target),
        file_sha256=digest_submitted,
    )
    assert digest_accepted["success"] is True
    assert digest_audit.call_args.kwargs["params"]["file_sha256"] == digest_submitted
    assert digest_accepted["data"]["file_receipt"]["file_sha256"] == digest_sha
    for claimed, guidance in (
        ("f" * 63, handoff.GUIDANCE_SHA256_FORMAT),
        ("0" * 64, handoff.GUIDANCE_SHA256_MISMATCH),
    ):
        result, _ = await _put_digest(
            tools,
            subject_id,
            digest_file=str(digest_target),
            file_sha256=claimed,
        )
        _assert_batch(result, handoff.BATCH_SHA256_MISMATCH)
        assert result["error"] == guidance
        review_result, _ = await _review(
            tools,
            subject_id,
            prev_version=1,
            review_file=str(target),
            file_sha256=claimed,
        )
        _assert_batch(review_result, handoff.BATCH_SHA256_MISMATCH)
        assert review_result["error"] == guidance
    assert digest_sha != "0" * 64


@pytest.mark.asyncio
async def test_tc_mcp_406_true_escape_rejects_but_literal_and_short_escape_roundtrip(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path)
    marker = "ESCAPE_MARKER"
    encoded = json.dumps(_review_payload(marker), ensure_ascii=False).encode()
    true_escape = chr(92).encode() + b"u71ac"
    rejected_bytes = encoded.replace(marker.encode(), true_escape)
    rejected_path, rejected_sha = _write_bytes(tmp_path, "escaped.json", rejected_bytes)
    rejected, _ = await _review(
        tools,
        subject_id,
        review_file=str(rejected_path),
        file_sha256=rejected_sha,
    )
    _assert_batch(rejected, handoff.BATCH_ESCAPED_UNICODE_FOUND)
    assert await repo.get_review(subject_id) is None

    literal = "熬" + chr(92) * 2 + "u0041" + "\n短转义"
    accepted_path, accepted_sha = _write_json(
        tmp_path, "literal.json", _review_payload(literal)
    )
    accepted, _ = await _review(
        tools,
        subject_id,
        review_file=str(accepted_path),
        file_sha256=accepted_sha,
    )
    assert accepted["success"] is True
    stored = await repo.get_review(subject_id)
    assert stored is not None
    assert stored.sections[0].body == literal

    digest_encoded = json.dumps(_digest_payload(marker), ensure_ascii=False).encode()
    digest_rejected_raw = digest_encoded.replace(marker.encode(), true_escape)
    digest_rejected_path, digest_rejected_sha = _write_bytes(
        tmp_path, "digest_escaped.json", digest_rejected_raw
    )
    digest_rejected, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_rejected_path),
        file_sha256=digest_rejected_sha,
    )
    _assert_batch(digest_rejected, handoff.BATCH_ESCAPED_UNICODE_FOUND)
    digest_literal_path, digest_literal_sha = _write_json(
        tmp_path, "digest_literal.json", _digest_payload(literal)
    )
    digest_accepted, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_literal_path),
        file_sha256=digest_literal_sha,
    )
    assert digest_accepted["success"] is True
    stored_digest = await repo.get_digest(subject_id, start=_BASE, end=_END)
    assert stored_digest is not None and stored_digest.digest_text == literal


@pytest.mark.asyncio
async def test_tc_mcp_407_invalid_json_variants_match_shared_guidance(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    variants = (
        (b"\xef\xbb\xbf{}", handoff.GUIDANCE_JSON_BOM),
        (b"\xff\xfe{}", handoff.GUIDANCE_JSON_NOT_UTF8),
        (b'{"sections":[}', handoff.GUIDANCE_JSON_SYNTAX),
    )
    for index, (raw, guidance) in enumerate(variants):
        target, sha256 = _write_bytes(tmp_path, f"invalid_{index}.json", raw)
        for result in (
            (await _review(tools, subject_id, review_file=str(target), file_sha256=sha256))[0],
            (await _put_digest(tools, subject_id, digest_file=str(target), file_sha256=sha256))[0],
        ):
            _assert_batch(result, handoff.BATCH_INVALID_JSON)
            assert result["error"] == guidance


@pytest.mark.asyncio
async def test_tc_mcp_408_payload_shape_is_strict_and_never_uses_array_category(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    cases = (
        ([], "顶层是数组"),
        ("text", "顶层是字符串"),
        ({"trend": {}}, "缺必需键 sections"),
        ({"sections": [], "section": []}, "含未知键 section"),
    )
    for index, (payload, problem) in enumerate(cases):
        target, sha256 = _write_json(tmp_path, f"shape_review_{index}.json", payload)
        result, _ = await _review(
            tools,
            subject_id,
            review_file=str(target),
            file_sha256=sha256,
        )
        _assert_batch(result, handoff.BATCH_INVALID_PAYLOAD_SHAPE)
        assert problem in result["error"]
        assert result["batch_category"] != handoff.BATCH_NOT_AN_ARRAY

    digest_cases = (
        ([], "顶层是数组"),
        ({"highlights": []}, "缺必需键 digest_text"),
        ({"digest_text": "正文", "summary": "错键"}, "含未知键 summary"),
    )
    for index, (payload, problem) in enumerate(digest_cases):
        target, sha256 = _write_json(tmp_path, f"shape_digest_{index}.json", payload)
        result, _ = await _put_digest(
            tools,
            subject_id,
            digest_file=str(target),
            file_sha256=sha256,
        )
        _assert_batch(result, handoff.BATCH_INVALID_PAYLOAD_SHAPE)
        assert problem in result["error"]


@pytest.mark.asyncio
async def test_tc_mcp_409_permission_gate_prevents_any_file_read(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    fifo = handoff.handoff_dir(tmp_path) / "permission_pipe.json"
    os.mkfifo(fifo)
    denied = error_response("权限不足", "permission")
    with patch("src.mcp.handoff.load_handoff_file") as loader:
        for tool_name, file_key in (
            ("put_subject_review", "review_file"),
            ("put_subject_digest", "digest_file"),
        ):
            kwargs: dict[str, Any] = {
                "subject_id": subject_id,
                "file_sha256": "0" * 64,
                file_key: str(fifo),
            }
            if tool_name == "put_subject_review":
                kwargs.update(prev_version=0, covered_until=_END.isoformat())
            else:
                kwargs.update(
                    interval_start=_BASE.isoformat(),
                    interval_end=_END.isoformat(),
                )
            result, audit = await _invoke(tools[tool_name], denied=denied, **kwargs)
            assert result["error_type"] == "permission"
            assert "batch_category" not in result
            assert audit.call_args.kwargs["error"] == "permission"
    loader.assert_not_called()


@pytest.mark.asyncio
async def test_tc_mcp_410_review_file_gates_precede_optimistic_lock(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    first_path, first_sha = _write_json(tmp_path, "review_v1.json", _review_payload("版本一"))
    first, _ = await _review(
        tools,
        subject_id,
        review_file=str(first_path),
        file_sha256=first_sha,
    )
    assert first["data"]["version"] == 1

    good_path, good_sha = _write_json(tmp_path, "review_good.json", _review_payload("版本二"))
    conflict, _ = await _review(
        tools,
        subject_id,
        prev_version=99,
        review_file=str(good_path),
        file_sha256=good_sha,
    )
    assert conflict["error_type"] == "conflict"
    assert conflict["latest_version"] == 1
    assert "batch_category" not in conflict

    bad_sha, _ = await _review(
        tools,
        subject_id,
        prev_version=99,
        review_file=str(good_path),
        file_sha256="0" * 64,
    )
    _assert_batch(bad_sha, handoff.BATCH_SHA256_MISMATCH)
    shape_path, shape_sha = _write_json(
        tmp_path, "review_shape.json", {"sections": [], "unknown": True}
    )
    shape, _ = await _review(
        tools,
        subject_id,
        prev_version=99,
        review_file=str(shape_path),
        file_sha256=shape_sha,
    )
    _assert_batch(shape, handoff.BATCH_INVALID_PAYLOAD_SHAPE)


def test_tc_mcp_411_412_helper_constants_and_footprints_are_locked() -> None:
    assert handoff.BATCH_INVALID_PAYLOAD_SHAPE == "invalid_payload_shape"
    template = handoff.GUIDANCE_INVALID_PAYLOAD_SHAPE_TEMPLATE
    assert template == (
        "交接文件顶层结构不符：{problem}。文件顶层必须是单个 JSON 对象；"
        "必需键与可选键的全集见工具说明书，键全集之外的未知键一律拒收"
        "（防键名转写错导致正文静默丢失）。请按说明书键全集重写为新文件后重提"
        "（勿覆盖原文件——被拒文件保留作排查物证）；内容无需重新生成。"
    )
    probe = "summaries" + "_file"
    for forbidden in ("review_file", "digest_file", "sections", "digest_text", probe):
        assert forbidden not in template
    assert not any(ord(char) < 32 for char in template)
    assert chr(92) not in template

    root = Path(__file__).parents[2]
    candidates = [
        *root.joinpath("src/mcp").rglob("*.py"),
        *root.joinpath("tests/mcp").rglob("*.py"),
        *root.joinpath("tests/mcp").rglob("*.json"),
    ]
    handoff_hits = {
        path.relative_to(root)
        for path in candidates
        if re.search(r"\bhandoff\b", path.read_text())
    }
    upstream_hits = {
        path.relative_to(root) for path in candidates if probe in path.read_text()
    }
    assert len(handoff_hits) == 7
    assert len(upstream_hits) == 4


def test_tc_mcp_415_docstrings_expose_frozen_operator_contract() -> None:
    from src.mcp.server import create_mcp_server

    registered = create_mcp_server()._tool_manager._tools
    review_doc = inspect.getdoc(registered["put_subject_review"].fn) or ""
    digest_doc = inspect.getdoc(registered["put_subject_digest"].fn) or ""
    categories = (
        "invalid_param_combo",
        "path_not_allowed",
        "file_unreadable",
        "file_too_large",
        "sha256_mismatch",
        "escaped_unicode_found",
        "invalid_json",
        "invalid_payload_shape",
    )
    for doc, file_key in ((review_doc, "review_file"), (digest_doc, "digest_file")):
        assert file_key in doc
        assert "UTF-8 无 BOM" in doc
        assert "同机要求" in doc
        assert "file_receipt" in doc
        assert "被拒后文件复用规则" in doc
        assert "成功后服务端不动交接文件" in doc
        assert all(category in doc for category in categories)
        assert "not_an_array" not in doc


@pytest.mark.asyncio
async def test_tc_subj_379_380_parameter_channel_remains_compatible(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    review, review_audit = await _review(
        tools,
        subject_id,
        sections=json.dumps([{"title": "参数", "body": "综述参数通道"}]),
        trend=json.dumps({"emerging": ["新"], "fading": []}),
    )
    assert review == {"success": True, "data": {"subject_id": subject_id, "version": 1}}
    assert review_audit.call_args.kwargs["params"] == {"subject_id": subject_id}

    digest, digest_audit = await _put_digest(
        tools,
        subject_id,
        digest_text="滚动参数通道",
        highlights=json.dumps([]),
    )
    assert digest["success"] is True
    assert "file_receipt" not in digest["data"]
    assert digest_audit.call_args.kwargs["params"] == {"subject_id": subject_id}
    missing, _ = await _put_digest(tools, subject_id)
    empty, _ = await _put_digest(tools, subject_id, digest_text="")
    assert missing == empty


@pytest.mark.asyncio
async def test_tc_subj_381_387_review_version_chain_and_channel_reverse(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path)
    first, first_audit = await _review(
        tools, subject_id, sections=[{"title": "A", "body": "参数一"}]
    )
    file_path, file_sha = _write_json(tmp_path, "review_b.json", _review_payload("文件二"))
    second, _ = await _review(
        tools,
        subject_id,
        prev_version=1,
        review_file=str(file_path),
        file_sha256=file_sha,
    )
    conflict, _ = await _review(
        tools,
        subject_id,
        prev_version=0,
        review_file=str(file_path),
        file_sha256=file_sha,
    )
    third, third_audit = await _review(
        tools,
        subject_id,
        prev_version=2,
        sections=[{"title": "A", "body": "参数三"}],
    )

    assert [first["data"]["version"], second["data"]["version"], third["data"]["version"]] == [
        1,
        2,
        3,
    ]
    assert conflict["error_type"] == "conflict"
    assert conflict["latest_version"] == 2
    assert set(first["data"]) == set(third["data"])
    assert "file_receipt" in second["data"] and "file_receipt" not in third["data"]
    assert first_audit.call_args.kwargs["params"] == {"subject_id": subject_id}
    assert third_audit.call_args.kwargs["params"] == {"subject_id": subject_id}
    stored = await repo.get_review(subject_id)
    assert stored is not None and stored.version == 3
    assert stored.sections[0].body == "参数三"


@pytest.mark.asyncio
async def test_tc_subj_382_citations_stay_under_existing_business_gate(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path, "t1", "t2")
    review_payload = _review_payload()
    review_payload["cited"] = ["t1", "outside"]
    review_path, review_sha = _write_json(tmp_path, "review_cited.json", review_payload)
    review, _ = await _review(
        tools,
        subject_id,
        review_file=str(review_path),
        file_sha256=review_sha,
    )
    assert review["error_type"] == "validation"
    assert "outside" in review["error"]
    assert "batch_category" not in review

    digest_payload = _digest_payload()
    digest_payload["highlights"] = [
        {"point": "越界", "cited_tweet_ids": ["outside"]},
    ]
    digest_path, digest_sha = _write_json(tmp_path, "digest_cited.json", digest_payload)
    digest, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_path),
        file_sha256=digest_sha,
    )
    assert digest["error_type"] == "validation"
    assert "outside" in digest["error"]
    assert "batch_category" not in digest

    valid_payload = _review_payload("合法去重")
    valid_payload["cited"] = [" t1 ", "t1", "t2"]
    valid_path, valid_sha = _write_json(tmp_path, "review_cited_valid.json", valid_payload)
    valid, _ = await _review(
        tools,
        subject_id,
        review_file=str(valid_path),
        file_sha256=valid_sha,
    )
    assert valid["success"] is True
    stored = await FileSubjectStore(tmp_path).get_review(subject_id)
    assert stored is not None and stored.cited_tweet_ids == ["t1", "t2"]


@pytest.mark.asyncio
async def test_tc_subj_383_four_thousand_character_business_boundaries(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    review_path, review_sha = _write_json(tmp_path, "review_4000.json", _review_payload("甲" * 4000))
    review_ok, _ = await _review(
        tools,
        subject_id,
        review_file=str(review_path),
        file_sha256=review_sha,
    )
    assert review_ok["success"] is True
    too_long_path, too_long_sha = _write_json(
        tmp_path, "review_4001.json", _review_payload("甲" * 4001)
    )
    review_bad, _ = await _review(
        tools,
        subject_id,
        prev_version=1,
        review_file=str(too_long_path),
        file_sha256=too_long_sha,
    )
    assert review_bad["error"] == "第 1 段 body 超过 4000 字上限"
    assert "batch_category" not in review_bad

    digest_path, digest_sha = _write_json(tmp_path, "digest_4000.json", _digest_payload("乙" * 4000))
    digest_ok, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_path),
        file_sha256=digest_sha,
    )
    assert digest_ok["success"] is True
    digest_bad_path, digest_bad_sha = _write_json(
        tmp_path, "digest_4001.json", _digest_payload("乙" * 4001)
    )
    digest_bad, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_bad_path),
        file_sha256=digest_bad_sha,
    )
    assert digest_bad["error"] == "digest_text 超过 4000 字上限"


@pytest.mark.asyncio
async def test_tc_subj_384_provenance_is_validated_after_file_gates(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path, "t1", "t2")
    candidate_hash = build_candidate_set_hash(["t1", "t2"])
    provenance = {
        "playbook_id": "xw-review",
        "playbook_version": "test",
        "prompt_hash": _PROMPT_HASH,
        "candidate_set_hash": candidate_hash,
        "candidate_ids": "t1,t2",
        "model_name": "test-model",
        "model_version": "fixed",
    }
    review_path, review_sha = _write_json(tmp_path, "review_provenance.json", _review_payload())
    accepted, _ = await _review(
        tools,
        subject_id,
        review_file=str(review_path),
        file_sha256=review_sha,
        **provenance,
    )
    assert accepted["data"]["provenance_written"] is True
    assert "file_receipt" in accepted["data"]

    digest_path, digest_sha = _write_json(tmp_path, "digest_provenance.json", _digest_payload())
    digest_accepted, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_path),
        file_sha256=digest_sha,
        **provenance,
    )
    assert digest_accepted["data"]["provenance_written"] is True
    assert "file_receipt" in digest_accepted["data"]
    bad = dict(provenance, candidate_set_hash="0" * 64)
    rejected, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_path),
        file_sha256=digest_sha,
        **bad,
    )
    assert rejected["error_type"] == "validation"
    assert "候选集指纹不符" in rejected["error"]
    assert "batch_category" not in rejected
    review_rejected, _ = await _review(
        tools,
        subject_id,
        prev_version=1,
        review_file=str(review_path),
        file_sha256=review_sha,
        **bad,
    )
    assert review_rejected["error_type"] == "validation"
    assert "候选集指纹不符" in review_rejected["error"]
    assert "batch_category" not in review_rejected


@pytest.mark.asyncio
async def test_tc_subj_385_386_empty_and_value_type_states_remain_distinct(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    _, subject_id = await _subject(tmp_path)
    empty_path, empty_sha = _write_json(tmp_path, "empty.json", {})
    for result in (
        (await _review(tools, subject_id, review_file=str(empty_path), file_sha256=empty_sha))[0],
        (await _put_digest(tools, subject_id, digest_file=str(empty_path), file_sha256=empty_sha))[0],
    ):
        _assert_batch(result, handoff.BATCH_INVALID_PAYLOAD_SHAPE)

    review_empty_path, review_empty_sha = _write_json(
        tmp_path, "review_empty.json", {"sections": []}
    )
    review_empty, _ = await _review(
        tools,
        subject_id,
        review_file=str(review_empty_path),
        file_sha256=review_empty_sha,
    )
    assert review_empty["error"] == "sections 不能为空"
    assert "batch_category" not in review_empty

    digest_empty_path, digest_empty_sha = _write_json(
        tmp_path, "digest_empty.json", {"digest_text": "", "highlights": []}
    )
    digest_empty, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(digest_empty_path),
        file_sha256=digest_empty_sha,
    )
    assert digest_empty["error"] == "digest_text 不能为空"

    value_cases = (
        ("review", {"sections": "bad"}, "sections 必须是 JSON 数组"),
        ("review", {"sections": _review_payload()["sections"], "trend": []}, "trend 必须是 JSON 对象"),
        ("digest", {"digest_text": 7}, "digest_text 必须是字符串"),
        ("digest", {"digest_text": "ok", "highlights": {}}, "highlights 必须是 JSON 数组"),
        ("digest", {"digest_text": "ok", "cited": [7]}, "cited 必须是字符串数组"),
    )
    for index, (kind, payload, message) in enumerate(value_cases):
        target, sha256 = _write_json(tmp_path, f"type_{index}.json", payload)
        if kind == "review":
            result, _ = await _review(
                tools, subject_id, review_file=str(target), file_sha256=sha256
            )
        else:
            result, _ = await _put_digest(
                tools, subject_id, digest_file=str(target), file_sha256=sha256
            )
        assert result["error"] == message
        assert "batch_category" not in result


@pytest.mark.asyncio
async def test_tc_scn_118_review_file_roundtrip_preserves_long_chinese_payload(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path, "t1", "t2")
    literal = chr(92) * 2 + "u0041"
    sections = [
        {
            "title": f"第 {index + 1} 节",
            "body": f"熬·{literal}·" + "长正文" * 220,
            "cited_tweet_ids": ["t1"] if index == 0 else [],
        }
        for index in range(15)
    ]
    payload = {
        "sections": sections,
        "trend": {"emerging": ["新兴"], "fading": ["退潮"]},
        "cited": ["t1", "t2"],
    }
    target, sha256 = _write_json(tmp_path, "review_roundtrip.json", payload)
    result, _ = await _review(
        tools,
        subject_id,
        review_file=str(target),
        file_sha256=sha256,
    )
    assert result["success"] is True
    assert result["data"]["file_receipt"] == {"file_sha256": sha256, "item_count": 15}
    stored = await repo.get_review(subject_id)
    assert stored is not None
    assert [section.model_dump() for section in stored.sections] == sections
    assert stored.trend.model_dump() == payload["trend"]
    assert stored.cited_tweet_ids == payload["cited"]
    assert target.exists()


@pytest.mark.asyncio
async def test_tc_scn_119_digest_file_roundtrip_and_zero_item_receipt(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path, "t1", "t2")
    payload = {
        "digest_text": "熬：区间滚动新闻逐字回写",
        "highlights": [
            {"point": "要点一", "cited_tweet_ids": ["t1"]},
            {"point": "要点二", "cited_tweet_ids": ["t2"]},
            {"point": "要点三", "cited_tweet_ids": []},
        ],
        "cited": ["t1", "t2"],
    }
    target, sha256 = _write_json(tmp_path, "digest_roundtrip.json", payload)
    result, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(target),
        file_sha256=sha256,
    )
    assert result["success"] is True
    assert result["data"]["file_receipt"] == {"file_sha256": sha256, "item_count": 3}
    stored = await repo.get_digest(subject_id, start=_BASE, end=_END)
    assert stored is not None
    assert stored.digest_text == payload["digest_text"]
    assert [item.model_dump() for item in stored.highlights] == payload["highlights"]
    assert stored.cited_tweet_ids == payload["cited"]

    empty_path, empty_sha = _write_json(
        tmp_path, "digest_no_highlights.json", {"digest_text": "无要点也合法"}
    )
    empty, _ = await _put_digest(
        tools,
        subject_id,
        digest_file=str(empty_path),
        file_sha256=empty_sha,
    )
    assert empty["data"]["file_receipt"]["item_count"] == 0


@pytest.mark.asyncio
async def test_tc_subj_388_scn_120_rejection_preserves_file_and_store(
    tools: dict[str, Any], tmp_path: Path
) -> None:
    repo, subject_id = await _subject(tmp_path)
    first_path, first_sha = _write_json(tmp_path, "review_initial.json", _review_payload("初版"))
    first, _ = await _review(
        tools,
        subject_id,
        review_file=str(first_path),
        file_sha256=first_sha,
    )
    assert first["data"]["version"] == 1
    before = await repo.get_review(subject_id)
    assert before is not None

    marker = "ESCAPE_MARKER"
    encoded = json.dumps(_review_payload(marker), ensure_ascii=False).encode()
    raw = encoded.replace(marker.encode(), chr(92).encode() + b"u71ac")
    rejected_path, rejected_sha = _write_bytes(tmp_path, "review_rejected.json", raw)
    rejected, audit = await _review(
        tools,
        subject_id,
        prev_version=1,
        review_file=str(rejected_path),
        file_sha256=rejected_sha,
    )
    _assert_batch(rejected, handoff.BATCH_ESCAPED_UNICODE_FOUND)
    assert rejected_path.read_bytes() == raw
    assert audit.call_args.kwargs["error"] == handoff.BATCH_ESCAPED_UNICODE_FOUND
    after = await repo.get_review(subject_id)
    assert after == before

    corrected_path, corrected_sha = _write_json(
        tmp_path, "review_corrected.json", _review_payload("熬")
    )
    corrected, _ = await _review(
        tools,
        subject_id,
        prev_version=1,
        review_file=str(corrected_path),
        file_sha256=corrected_sha,
    )
    assert corrected["data"]["version"] == 2
    assert rejected_path.exists() and corrected_path.exists()
