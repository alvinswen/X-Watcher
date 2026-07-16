from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.mcp.helpers import error_response
from src.mcp.server import create_mcp_server
from src.subjects.models import EvalTier, SubjectEval
from src.subjects.services.eval_service import SubjectEvalService
from src.subjects.services.feedback_service import build_feedback_target_id
from src.subjects.store import FileSubjectStore


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Eval 议题",
        nl_description="验证 eval 账本",
    )
    return subject.subject_id


def _tool_funcs():
    mcp = create_mcp_server()
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def _load_tool_result(raw: str) -> dict:
    return json.loads(raw)


@pytest.mark.asyncio
async def test_put_eval_appends_and_get_filters_round_trip(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    service = SubjectEvalService(repo)
    target_id = build_feedback_target_id(
        "digest",
        subject_id=subject_id,
        interval_start="2026-07-01T00:00:00Z",
        time_axis="publish",
    )

    eval_record = await service.put_eval(
        subject_id=subject_id,
        target_id=target_id,
        tier="judge",
        scores='{"accuracy": 0.8}',
        target_provenance_ref="20260701T000000Z_publish_20260702081533123456Z",
        rubric_version="rubric-v1",
        judge_model="judge-test",
        judge_human_kappa=1,
        note="模型切换期",
    )

    assert re.fullmatch(r"ev_[0-9a-f]{8}", eval_record.id)
    assert eval_record.tier == EvalTier.judge
    assert eval_record.hard_fail is None
    assert eval_record.failed_checks == []
    assert eval_record.warnings == []
    assert eval_record.scores == {"accuracy": 0.8}

    shard = (
        tmp_path / "subjects" / subject_id / "eval" / f"{eval_record.when.strftime('%Y-%m')}.jsonl"
    )
    rows = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()]
    assert rows == [eval_record.model_dump(mode="json")]

    data = await service.get_evals(subject_id=subject_id, target_id=target_id, tier="judge")
    assert data["count"] == 1
    assert data["evals"][0] == eval_record.model_dump(mode="json")


@pytest.mark.asyncio
async def test_put_eval_validation_and_mcp_d2_reject(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    service = SubjectEvalService(repo)
    target_id = build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")

    with pytest.raises(ValueError, match="hygiene 档请调 run_subject_hygiene_check"):
        await service.put_eval(subject_id=subject_id, target_id=target_id, tier="hygiene")
    with pytest.raises(ValueError, match="judge_human_kappa"):
        await service.put_eval(
            subject_id=subject_id,
            target_id=target_id,
            tier="human",
            judge_human_kappa=1.01,
        )
    with pytest.raises(ValueError, match="scores"):
        await service.put_eval(
            subject_id=subject_id,
            target_id=target_id,
            tier="human",
            scores='{"bad": "nope"}',
        )
    with pytest.raises(ValueError, match="target_id"):
        await service.put_eval(subject_id=subject_id, target_id="digest:bad", tier="judge")
    with pytest.raises(LookupError, match="议题不存在"):
        await service.put_eval(subject_id="sub_missing", target_id=target_id, tier="judge")

    tools = _tool_funcs()
    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        result = _load_tool_result(
            await tools["put_subject_eval"](
                subject_id=subject_id,
                target_id=target_id,
                tier="judge",
                hard_fail=False,
            )
        )

    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert "hard_fail" in result["error"]
    assert await repo.read_evals(subject_id) == []


@pytest.mark.asyncio
async def test_mcp_eval_io_failure_returns_internal_and_does_not_persist(tmp_path, monkeypatch):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    target_id = build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")

    async def fail_append(_eval_record: SubjectEval) -> SubjectEval:
        raise OSError("disk full")

    monkeypatch.setattr(repo, "append_eval", fail_append)
    tools = _tool_funcs()
    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        result = _load_tool_result(
            await tools["put_subject_eval"](
                subject_id=subject_id,
                target_id=target_id,
                tier="human",
                scores='{"manual_score": 1}',
            )
        )

    assert result["success"] is False
    assert result["error_type"] == "internal"
    assert "写入失败" in result["error"]
    assert "disk full" not in result["error"]
    assert await repo.read_evals(subject_id) == []


@pytest.mark.asyncio
async def test_eval_tools_permission_matrix_and_read_empty_state(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    target_id = build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")
    tools = _tool_funcs()

    with (
        patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo),
        patch(
            "src.mcp.tools.subject_tools.require_scope",
            return_value=error_response("权限不足", "permission"),
        ),
    ):
        put_denied = _load_tool_result(
            await tools["put_subject_eval"](
                subject_id=subject_id,
                target_id=target_id,
                tier="judge",
            )
        )
        hygiene_denied = _load_tool_result(
            await tools["run_subject_hygiene_check"](
                subject_id=subject_id,
                target_type="digest",
            )
        )
        read_eval = _load_tool_result(await tools["get_subject_eval"](subject_id=subject_id))
        correction = _load_tool_result(
            await tools["get_subject_correction_rate"](
                subject_id=subject_id,
                window_days=7,
            )
        )

    assert put_denied["error_type"] == "permission"
    assert hygiene_denied["error_type"] == "permission"
    assert read_eval["success"] is True
    assert read_eval["data"]["count"] == 0
    assert correction["success"] is True
    assert correction["data"]["total"]["not_applicable"] is True
    assert await repo.read_evals(subject_id) == []


@pytest.mark.asyncio
async def test_eval_shards_append_only_sort_and_bad_line_skip(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    target_id = build_feedback_target_id("review", subject_id=subject_id, version=1)
    old = SubjectEval(
        id="ev_old0001",
        subject_id=subject_id,
        target_id=target_id,
        tier=EvalTier.human,
        scores={},
        when=datetime(2026, 6, 30, 23, 59, tzinfo=UTC),
    )
    new = old.model_copy(
        update={
            "id": "ev_new0001",
            "scores": {"quality": 1.0},
            "when": datetime(2026, 7, 1, 0, 1, tzinfo=UTC),
        }
    )
    await repo.append_eval(old)
    await repo.append_eval(new)

    june = tmp_path / "subjects" / subject_id / "eval" / "2026-06.jsonl"
    with june.open("a", encoding="utf-8") as fh:
        fh.write("{not-json}\n")

    evals = await repo.read_evals(subject_id)
    assert [item.id for item in evals] == ["ev_old0001", "ev_new0001"]
    data = await SubjectEvalService(repo).get_evals(
        subject_id=subject_id,
        since=datetime(2026, 7, 1, tzinfo=UTC) - timedelta(seconds=1),
        until=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert data["count"] == 1
    assert data["evals"][0]["id"] == "ev_new0001"
