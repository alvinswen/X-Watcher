"""信源候选挖掘服务测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.source_candidates.infrastructure.file_source_candidate_repository import (
    FileSourceCandidateStore,
)
from src.source_candidates.services.mining_service import MiningService
from src.subjects.store import FileSubjectStore


def _write_rows(tmp_path, rows):
    shard = tmp_path / "tweets" / "source" / "2026-08.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _row(tweet_id, source, target, reference_type="quoted"):
    return {
        "tweet_id": tweet_id,
        "author_username": source,
        "referenced_tweet_author_username": target,
        "reference_type": reference_type,
        "created_at": datetime(2026, 8, 2, 12, tzinfo=UTC).isoformat(),
    }


@pytest.mark.asyncio
async def test_default_threshold_and_signal_scope(tmp_path):
    _write_rows(
        tmp_path,
        [
            _row("1", "source_a", "CandidateA"),
            _row("2", "source_a", "CandidateA"),
            _row("3", "source_b", "CandidateA", "retweeted"),
            _row("4", "source_a", "CandidateB"),
            _row("5", "source_b", "CandidateB"),
            _row("6", "source_a", "CandidateC"),
            _row("7", "source_a", "CandidateC"),
            _row("8", "source_a", "CandidateC"),
            _row("9", "source_a", "CandidateC"),
            _row("10", "source_a", "CandidateC"),
            _row("11", "source_a", "CandidateD", "replied_to"),
            _row("12", "self", "self"),
        ],
    )
    store = FileSourceCandidateStore(tmp_path)
    service = MiningService(
        store,
        FileFollowStore(tmp_path),
        FileSubjectStore(tmp_path),
    )

    result = await service.mine()

    assert [item["candidate_id"] for item in result["mined"]] == ["candidatea"]
    assert result["stats"]["above_threshold"] == 1
    candidate = await store.get_candidate("candidatea")
    assert candidate is not None
    assert candidate.mining.citation_total == 3
    assert candidate.mining.source_diversity == 2
    assert candidate.mining.first_discovered_at.utcoffset() is not None


@pytest.mark.asyncio
async def test_terminal_library_suppression_and_nonterminal_merge_are_idempotent(tmp_path):
    _write_rows(
        tmp_path,
        [
            _row("1", "source_a", "CandidateA"),
            _row("2", "source_a", "CandidateA"),
            _row("3", "source_b", "CandidateA"),
        ],
    )
    store = FileSourceCandidateStore(tmp_path)
    service = MiningService(
        store,
        FileFollowStore(tmp_path),
        FileSubjectStore(tmp_path),
    )

    first = await service.mine()
    second = await service.mine()

    assert first["stats"]["admitted"] == 1
    assert second["mined"] == []
    assert second["merged_refreshed"] == ["candidatea"]
    candidate = await store.get_candidate("candidatea")
    assert candidate is not None
    assert candidate.mining.citation_total == 3
    assert candidate.mining.source_diversity == 2
