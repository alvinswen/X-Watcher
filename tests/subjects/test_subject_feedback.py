from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.mcp.server import create_mcp_server
from src.subjects.models import (
    FeedbackAuthority,
    FeedbackTargetType,
    FeedbackVerdict,
    SubjectFeedback,
)
from src.subjects.services.feedback_service import (
    SubjectFeedbackService,
    build_feedback_target_id,
)
from src.subjects.store import FileSubjectStore


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Feedback 议题",
        nl_description="验证人工与 Agent 裁决落盘",
    )
    return subject.subject_id


def _tool_funcs():
    mcp = create_mcp_server()
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def _load_tool_result(raw: str) -> dict:
    return json.loads(raw)


def _feedback_line_count(root: Path, subject_id: str) -> int:
    base = root / "subjects" / subject_id / "feedback"
    return sum(len(path.read_text(encoding="utf-8").splitlines()) for path in base.glob("*.jsonl"))


def _feedback(
    *,
    subject_id: str,
    feedback_id: str,
    target_id: str,
    when: datetime,
    supersedes: str | None = None,
    verdict: FeedbackVerdict = FeedbackVerdict.reject,
) -> SubjectFeedback:
    return SubjectFeedback(
        id=feedback_id,
        subject_id=subject_id,
        target_type=FeedbackTargetType.match,
        target_id=target_id,
        verdict=verdict,
        authority=FeedbackAuthority.human_correction,
        who="human:alvin",
        supersedes=supersedes,
        when=when,
    )


@pytest.mark.asyncio
async def test_put_feedback_appends_and_returns_generated_fields(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    service = SubjectFeedbackService(repo)
    target_id = build_feedback_target_id(
        "digest",
        subject_id=subject_id,
        interval_start=datetime(2026, 6, 22, 16, tzinfo=UTC),
        time_axis="publish",
    )

    feedback = await service.put_feedback(
        subject_id=subject_id,
        target_type="digest",
        target_id=target_id,
        verdict="correct",
        authority="human_correction",
        who="human:alvin",
        provenance_key="20260622T160000Z_publish_20260702031400123456Z",
        corrected_value='{"relevance": 0.2}',
        note="引用了无关推文",
    )

    assert re.fullmatch(r"fb_[0-9a-f]{8}", feedback.id)
    assert feedback.when.tzinfo is not None
    assert feedback.target_id == target_id
    assert feedback.corrected_value == {"relevance": 0.2}

    shard = tmp_path / "subjects" / subject_id / "feedback" / "2026-07.jsonl"
    rows = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()]
    assert rows == [feedback.model_dump(mode="json")]


@pytest.mark.asyncio
async def test_supersedes_round_trip_single_and_multi_hop(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    service = SubjectFeedbackService(repo)
    target_id = build_feedback_target_id(
        "match",
        subject_id=subject_id,
        tweet_id="1799000000000000001",
    )

    first = await service.put_feedback(
        subject_id=subject_id,
        target_type="match",
        target_id=target_id,
        verdict="reject",
        authority="human_correction",
        who="human:alvin",
    )
    second = await service.put_feedback(
        subject_id=subject_id,
        target_type="match",
        target_id=target_id,
        verdict="accept",
        authority="human_correction",
        who="human:alvin",
        supersedes=first.id,
    )

    current, cycles = await service.get_current_feedbacks(subject_id=subject_id)
    assert cycles == []
    assert [item["id"] for item in current] == [second.id]
    assert current[0]["verdict"] == "accept"
    assert current[0]["superseded_from"] == [first.id]

    third = await service.put_feedback(
        subject_id=subject_id,
        target_type="match",
        target_id=target_id,
        verdict="off_topic",
        authority="human_correction",
        who="human:alvin",
        supersedes=second.id,
    )
    current, cycles = await service.get_current_feedbacks(subject_id=subject_id)
    assert cycles == []
    assert [item["id"] for item in current] == [third.id]
    assert current[0]["superseded_from"] == [second.id, first.id]
    assert _feedback_line_count(tmp_path, subject_id) == 3


@pytest.mark.asyncio
async def test_validation_matrix_and_missing_subject(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    service = SubjectFeedbackService(repo)
    target_id = build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")

    invalid_cases = [
        ({"target_type": "summary"}, "target_type 只能是 match / digest / review"),
        ({"verdict": "maybe"}, "verdict 只能是 reject / accept / correct / off_topic / drift"),
        ({"authority": "admin"}, "authority 只能是 human_correction / agent_selfeval"),
        ({"who": "alvin"}, "who 需形如 human:<名> 或 agent:<名>"),
        ({"who": "human:"}, "who 需形如 human:<名> 或 agent:<名>"),
        ({"who": ""}, "who 需形如 human:<名> 或 agent:<名>"),
        (
            {"authority": "human_correction", "who": "agent:bot"},
            "human_correction 的 who 须以 human: 开头",
        ),
        (
            {"authority": "agent_selfeval", "who": "human:alvin"},
            "agent_selfeval 的 who 须以 agent: 开头",
        ),
        (
            {"verdict": "correct", "corrected_value": "{relevance:0.2}"},
            "corrected_value 需为合法 JSON 字符串",
        ),
    ]
    base_kwargs = {
        "subject_id": subject_id,
        "target_type": "match",
        "target_id": target_id,
        "verdict": "reject",
        "authority": "human_correction",
        "who": "human:alvin",
    }
    for override, message in invalid_cases:
        with pytest.raises(ValueError, match=re.escape(message)):
            await service.put_feedback(**{**base_kwargs, **override})

    await service.put_feedback(**base_kwargs)
    await service.put_feedback(
        subject_id=subject_id,
        target_type="match",
        target_id=build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_2"),
        verdict="drift",
        authority="agent_selfeval",
        who="agent:judge",
    )
    with pytest.raises(LookupError, match="议题不存在"):
        await service.put_feedback(**{**base_kwargs, "subject_id": "sub_missing"})


@pytest.mark.asyncio
async def test_three_target_coordinates_filters_empty_and_hanging_supersedes(tmp_path):
    repo = FileSubjectStore(tmp_path)
    empty_subject_id = await _subject(repo)
    subject_id = await _subject(repo)
    service = SubjectFeedbackService(repo)

    assert await service.get_current_feedbacks(subject_id=empty_subject_id) == ([], [])
    with pytest.raises(LookupError, match="议题不存在"):
        await service.get_current_feedbacks(subject_id="sub_missing")

    targets = [
        ("match", build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")),
        (
            "digest",
            build_feedback_target_id(
                "digest",
                subject_id=subject_id,
                interval_start="2026-06-22T16:00:00Z",
                time_axis="publish",
            ),
        ),
        ("review", build_feedback_target_id("review", subject_id=subject_id, version=7)),
    ]
    for target_type, target_id in targets:
        await service.put_feedback(
            subject_id=subject_id,
            target_type=target_type,
            target_id=target_id,
            verdict="accept",
            authority="human_correction",
            who="human:alvin",
            supersedes="fb_deadbeef",
        )

    all_feedbacks, cycles = await service.get_current_feedbacks(subject_id=subject_id)
    assert cycles == []
    assert {item["target_id"] for item in all_feedbacks} == {target for _, target in targets}
    assert all(item["superseded_from"] == [] for item in all_feedbacks)

    digest_feedbacks, _ = await service.get_current_feedbacks(
        subject_id=subject_id,
        target_type="digest",
    )
    assert [item["target_type"] for item in digest_feedbacks] == ["digest"]

    match_feedbacks, _ = await service.get_current_feedbacks(
        subject_id=subject_id,
        target_id=targets[0][1],
    )
    assert [item["target_id"] for item in match_feedbacks] == [targets[0][1]]


@pytest.mark.asyncio
async def test_append_only_and_cross_month_bad_line_read(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    service = SubjectFeedbackService(repo)
    target_id = build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")

    first = await service.put_feedback(
        subject_id=subject_id,
        target_type="match",
        target_id=target_id,
        verdict="reject",
        authority="human_correction",
        who="human:alvin",
    )
    second = await service.put_feedback(
        subject_id=subject_id,
        target_type="match",
        target_id=target_id,
        verdict="reject",
        authority="human_correction",
        who="human:alvin",
    )
    assert first.id != second.id
    assert _feedback_line_count(tmp_path, subject_id) == 2

    old = _feedback(
        subject_id=subject_id,
        feedback_id="fb_old0001",
        target_id="match::old::tw",
        when=datetime(2026, 5, 31, 23, 59, tzinfo=UTC),
    )
    new = _feedback(
        subject_id=subject_id,
        feedback_id="fb_new0001",
        target_id="match::old::tw",
        when=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
        supersedes=old.id,
        verdict=FeedbackVerdict.accept,
    )
    await repo.append_feedback(old)
    await repo.append_feedback(new)
    may_shard = tmp_path / "subjects" / subject_id / "feedback" / "2026-05.jsonl"
    with may_shard.open("a", encoding="utf-8") as fh:
        fh.write("{not-json}\n")

    current, cycles = await service.get_current_feedbacks(
        subject_id=subject_id,
        target_id="match::old::tw",
    )
    assert cycles == []
    assert [item["id"] for item in current] == [new.id]
    assert current[0]["superseded_from"] == [old.id]


@pytest.mark.asyncio
async def test_mcp_put_io_failure_returns_internal_and_does_not_persist(tmp_path, monkeypatch):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)

    async def fail_append(_feedback: SubjectFeedback) -> SubjectFeedback:
        raise OSError("disk full")

    monkeypatch.setattr(repo, "append_feedback", fail_append)
    tools = _tool_funcs()
    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        result = _load_tool_result(
            await tools["put_subject_feedback"](
                subject_id=subject_id,
                target_type="digest",
                target_id=build_feedback_target_id(
                    "digest",
                    subject_id=subject_id,
                    interval_start="2026-06-22T16:00:00Z",
                    time_axis="publish",
                ),
                verdict="reject",
                authority="human_correction",
                who="human:alvin",
            )
        )

    assert result["success"] is False
    assert result["error_type"] == "internal"
    assert "写入失败" in result["error"]
    assert "disk full" not in result["error"]
    assert await repo.read_feedbacks(subject_id) == []


@pytest.mark.asyncio
async def test_mcp_get_cycle_falls_back_to_latest_and_audits_warning(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    target_id = build_feedback_target_id("match", subject_id=subject_id, tweet_id="tw_1")
    first = _feedback(
        subject_id=subject_id,
        feedback_id="fb_cycle1",
        target_id=target_id,
        when=datetime(2026, 7, 2, 1, tzinfo=UTC),
        supersedes="fb_cycle2",
    )
    second = _feedback(
        subject_id=subject_id,
        feedback_id="fb_cycle2",
        target_id=target_id,
        when=datetime(2026, 7, 2, 2, tzinfo=UTC),
        supersedes="fb_cycle1",
        verdict=FeedbackVerdict.accept,
    )
    await repo.append_feedback(first)
    await repo.append_feedback(second)

    tools = _tool_funcs()
    with (
        patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo),
        patch("src.mcp.tools.subject_tools.audit_log") as audit_log,
    ):
        result = _load_tool_result(await tools["get_subject_feedback"](subject_id=subject_id))

    assert result["success"] is True
    assert [item["id"] for item in result["data"]["feedbacks"]] == [second.id]
    assert result["data"]["feedbacks"][0]["superseded_from"] == [first.id]
    assert any(
        call.kwargs.get("error") == "superseded_cycle_detected" for call in audit_log.call_args_list
    )


def test_static_feedback_boundaries_and_helper_definition():
    root = Path(__file__).resolve().parents[2]
    service_source = (root / "src" / "subjects" / "services" / "feedback_service.py").read_text(
        encoding="utf-8"
    )
    assert service_source.count("def build_feedback_target_id") == 1

    p010 = re.compile(r"_DATA\b|MOCK_|FALLBACK_|DEFAULT_[A-Z]")
    for rel_path in [
        "src/subjects/services/feedback_service.py",
        "src/subjects/store.py",
        "src/mcp/tools/subject_tools.py",
    ]:
        assert not p010.search((root / rel_path).read_text(encoding="utf-8"))
