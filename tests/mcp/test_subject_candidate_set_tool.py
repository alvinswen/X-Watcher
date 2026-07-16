from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.subjects.models import SubjectMatch
from src.subjects.provenance import build_candidate_set_hash
from src.subjects.store import FileSubjectStore

EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
PROMPT_HASH = "b" * 64
EXPECTED_KEYS = {
    "candidate_ids",
    "candidate_set_hash",
    "count",
    "time_axis",
    "interval_start",
    "interval_end",
    "skipped_no_publish_time",
}


def _tool_funcs():
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


async def _subject(repo: FileSubjectStore) -> str:
    subject = await repo.create_subject(
        name="Candidate Set MCP 议题",
        nl_description="验证候选集 MCP 工具",
    )
    return subject.subject_id


def _tweet_lookup(created_by_id: dict[str, datetime]):
    async def fake_get_tweets_by_ids(tweet_ids: list[str]):
        items = [
            {"tweet_id": tweet_id, "created_at": created_by_id[tweet_id]}
            for tweet_id in tweet_ids
            if tweet_id in created_by_id
        ]
        missing = [tweet_id for tweet_id in tweet_ids if tweet_id not in created_by_id]
        return items, missing

    return fake_get_tweets_by_ids


def _decode(result: str) -> dict:
    return json.loads(result)


def _provenance_args(candidate_data: dict) -> dict[str, str]:
    return {
        "playbook_id": "xw-candidate-set-test",
        "playbook_version": "2026.07",
        "prompt_hash": PROMPT_HASH,
        "candidate_set_hash": candidate_data["candidate_set_hash"],
        "candidate_ids": ",".join(candidate_data["candidate_ids"]),
        "model_name": "test-model",
        "model_version": "roundtrip",
    }


@pytest.mark.asyncio
async def test_candidate_set_tool_dispatches_axes_without_feed(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="pub_a",
                matched_at=base - timedelta(days=1),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="pub_b",
                matched_at=base + timedelta(minutes=5),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="ingest_only",
                matched_at=base + timedelta(minutes=15),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="missing_publish",
                matched_at=base + timedelta(minutes=20),
            ),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="at_end",
                matched_at=base + timedelta(hours=1),
            ),
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup(  # type: ignore[method-assign]
        {
            "pub_a": base + timedelta(minutes=5),
            "pub_b": base + timedelta(minutes=10),
            "ingest_only": base - timedelta(hours=1),
            "at_end": base + timedelta(hours=2),
        }
    )

    async def fail_get_subject_feed(*_args, **_kwargs):
        raise AssertionError("get_subject_candidate_set must not use get_subject_feed")

    repo.get_subject_feed = fail_get_subject_feed  # type: ignore[method-assign]
    tool = _tool_funcs()["get_subject_candidate_set"]

    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        publish = _decode(
            await tool(
                subject_id=subject_id,
                time_axis="publish",
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
            )
        )
        ingest = _decode(
            await tool(
                subject_id=subject_id,
                time_axis="ingest",
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
            )
        )
        review = _decode(await tool(subject_id=subject_id, time_axis="review"))

    assert publish["success"] is True
    publish_data = publish["data"]
    assert set(publish_data) == EXPECTED_KEYS
    assert publish_data["candidate_ids"] == ["pub_a", "pub_b"]
    assert publish_data["candidate_set_hash"] == build_candidate_set_hash(["pub_a", "pub_b"])
    assert publish_data["count"] == 2
    assert publish_data["time_axis"] == "publish"
    assert publish_data["interval_start"] == base.isoformat()
    assert publish_data["interval_end"] == (base + timedelta(hours=1)).isoformat()
    assert publish_data["skipped_no_publish_time"] == 1

    assert ingest["success"] is True
    ingest_data = ingest["data"]
    assert ingest_data["candidate_ids"] == ["ingest_only", "missing_publish", "pub_b"]
    assert ingest_data["candidate_set_hash"] == build_candidate_set_hash(
        ingest_data["candidate_ids"]
    )
    assert ingest_data["skipped_no_publish_time"] == 0

    assert review["success"] is True
    review_data = review["data"]
    assert review_data["candidate_ids"] == [
        "at_end",
        "ingest_only",
        "missing_publish",
        "pub_a",
        "pub_b",
    ]
    assert review_data["candidate_set_hash"] == build_candidate_set_hash(
        review_data["candidate_ids"]
    )
    assert review_data["interval_start"] is None
    assert review_data["interval_end"] is None


@pytest.mark.asyncio
async def test_candidate_set_tool_validation_not_found_and_review_interval_ignored(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    tool = _tool_funcs()["get_subject_candidate_set"]

    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        missing_interval = _decode(await tool(subject_id=subject_id, time_axis="publish"))
        partial_interval = _decode(
            await tool(
                subject_id=subject_id,
                time_axis="ingest",
                interval_start=base.isoformat(),
            )
        )
        review = _decode(
            await tool(
                subject_id=subject_id,
                time_axis="review",
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
            )
        )
        inverted = _decode(
            await tool(
                subject_id=subject_id,
                time_axis="publish",
                interval_start=(base + timedelta(hours=1)).isoformat(),
                interval_end=base.isoformat(),
            )
        )
        bad_axis = _decode(await tool(subject_id=subject_id, time_axis="match"))
        bad_time = _decode(
            await tool(
                subject_id=subject_id,
                time_axis="publish",
                interval_start="not-a-time",
                interval_end=base.isoformat(),
            )
        )
        missing_subject = _decode(await tool(subject_id="missing", time_axis="review"))

    for response in (missing_interval, partial_interval):
        assert response["success"] is False
        assert response["error_type"] == "validation"
        assert "该口径需提供 interval_start 与 interval_end" in response["error"]

    assert review["success"] is True
    assert review["data"]["interval_start"] is None
    assert review["data"]["interval_end"] is None

    assert inverted["success"] is False
    assert inverted["error_type"] == "validation"
    assert "区间倒置" in inverted["error"]

    assert bad_axis["success"] is False
    assert bad_axis["error_type"] == "validation"
    assert "time_axis 只能是 publish / ingest / review" in bad_axis["error"]

    assert bad_time["success"] is False
    assert bad_time["error_type"] == "validation"
    assert "参数解析失败" in bad_time["error"]

    assert missing_subject["success"] is False
    assert missing_subject["error_type"] == "not_found"
    assert "议题不存在" in missing_subject["error"]


@pytest.mark.asyncio
async def test_candidate_set_tool_empty_publish_skipped_and_audit(tmp_path):
    repo = FileSubjectStore(tmp_path)
    empty_subject_id = await _subject(repo)
    skipped_subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=skipped_subject_id,
                tweet_id="no_created_at",
                matched_at=base + timedelta(minutes=5),
            )
        ]
    )
    repo.get_tweets_by_ids = _tweet_lookup({})  # type: ignore[method-assign]
    tool = _tool_funcs()["get_subject_candidate_set"]

    with (
        patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo),
        patch("src.mcp.tools.subject_tools.audit_log") as audit_log,
    ):
        empty = _decode(await tool(subject_id=empty_subject_id, time_axis="review"))
        skipped = _decode(
            await tool(
                subject_id=skipped_subject_id,
                time_axis="publish",
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
            )
        )

    assert empty["success"] is True
    assert empty["data"]["candidate_ids"] == []
    assert empty["data"]["candidate_set_hash"] == EMPTY_HASH
    assert empty["data"]["count"] == 0

    assert skipped["success"] is True
    assert skipped["data"]["candidate_ids"] == []
    assert skipped["data"]["candidate_set_hash"] == EMPTY_HASH
    assert skipped["data"]["skipped_no_publish_time"] == 1
    audit_log.assert_any_call(
        "get_subject_candidate_set",
        "read",
        params={"subject_id": empty_subject_id, "time_axis": "review"},
    )


@pytest.mark.asyncio
async def test_candidate_set_ingest_hash_roundtrips_through_put_subject_digest(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(subject_id=subject_id, tweet_id="digest_a", matched_at=base),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="digest_b",
                matched_at=base + timedelta(minutes=10),
            ),
        ]
    )
    tools = _tool_funcs()

    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        candidate_result = _decode(
            await tools["get_subject_candidate_set"](
                subject_id=subject_id,
                time_axis="ingest",
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
            )
        )
        assert candidate_result["success"] is True
        candidate_data = candidate_result["data"]

        digest_result = _decode(
            await tools["put_subject_digest"](
                subject_id=subject_id,
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
                time_axis="ingest",
                digest_text="候选集 ingest 闭环摘要",
                cited="digest_a",
                **_provenance_args(candidate_data),
            )
        )

    assert candidate_data["candidate_ids"] == ["digest_a", "digest_b"]
    assert digest_result["success"] is True, digest_result
    assert digest_result["data"]["provenance_written"] is True


@pytest.mark.asyncio
async def test_candidate_set_review_hash_roundtrips_through_put_subject_review(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_id = await _subject(repo)
    base = datetime(2026, 7, 1, 10, tzinfo=UTC)
    await repo.upsert_matches(
        [
            SubjectMatch(subject_id=subject_id, tweet_id="review_a", matched_at=base),
            SubjectMatch(
                subject_id=subject_id,
                tweet_id="review_b",
                matched_at=base + timedelta(minutes=10),
            ),
        ]
    )
    tools = _tool_funcs()

    with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
        candidate_result = _decode(
            await tools["get_subject_candidate_set"](
                subject_id=subject_id,
                time_axis="review",
            )
        )
        assert candidate_result["success"] is True
        candidate_data = candidate_result["data"]

        review_result = _decode(
            await tools["put_subject_review"](
                subject_id=subject_id,
                prev_version=0,
                sections=[
                    {
                        "title": "候选集闭环",
                        "body": "review 口径 hash 可通过写入校验。",
                        "cited_tweet_ids": ["review_a"],
                    }
                ],
                covered_until=(base + timedelta(hours=1)).isoformat(),
                cited="review_a",
                **_provenance_args(candidate_data),
            )
        )

    assert candidate_data["candidate_ids"] == ["review_a", "review_b"]
    assert review_result["success"] is True, review_result
    assert review_result["data"]["version"] == 1
    assert review_result["data"]["provenance_written"] is True
