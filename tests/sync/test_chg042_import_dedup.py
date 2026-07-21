"""CHG-042 跨实例摘要导入入口去重。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.storage.jsonl_store import read_shard
from src.storage.paths import iter_summary_shards
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.sync.domain.models import ConflictStrategy
from src.sync.infrastructure.file_import_repository import FileImportStore


def _record(
    summary_id: str,
    tweet_id: str,
    *,
    text: str = "local",
) -> SummaryRecord:
    created_at = datetime(2026, 2, 1, tzinfo=UTC)
    return SummaryRecord(
        summary_id=summary_id,
        tweet_id=tweet_id,
        summary_text=text,
        translation_text=None,
        model_provider="test",
        model_name="test",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0,
        cached=False,
        is_generated_summary=True,
        content_hash=f"hash-{summary_id}",
        created_at=created_at,
        updated_at=created_at,
    )


def _item(summary_id: str, tweet_id: str, *, text: str = "remote") -> dict[str, object]:
    return _record(summary_id, tweet_id, text=text).model_dump(
        mode="json",
        exclude={"updated_at"},
    )


def _all_records(root: Path) -> list[dict[str, object]]:
    return [record for shard in iter_summary_shards(root) for record in read_shard(shard)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strategy",
    [ConflictStrategy.skip, ConflictStrategy.merge, ConflictStrategy.overwrite],
)
async def test_new_summary_id_for_existing_tweet_is_skipped_for_all_strategies(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    strategy: ConflictStrategy,
) -> None:
    local = _record("local-summary", "tweet-1")
    store = FileSummaryStore(tmp_path)
    await store.seed([local])

    with caplog.at_level(logging.INFO):
        stats = await FileImportStore(tmp_path).import_summaries(
            [_item("remote-summary", "tweet-1")],
            strategy,
        )

    assert stats.inserted == 0
    assert stats.updated == 0
    assert stats.skipped == 1
    assert stats.errors == 0
    assert _all_records(tmp_path) == [local.model_dump(mode="json")]
    assert "tweet-1" in caplog.text
    assert "remote-summary" in caplog.text
    assert "local-summary" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "expected_text", "expected_skipped", "expected_updated"),
    [
        (ConflictStrategy.skip, "local", 1, 0),
        (ConflictStrategy.merge, "local", 1, 0),
        (ConflictStrategy.overwrite, "remote", 0, 1),
    ],
)
async def test_existing_summary_id_keeps_prior_strategy_semantics(
    tmp_path: Path,
    strategy: ConflictStrategy,
    expected_text: str,
    expected_skipped: int,
    expected_updated: int,
) -> None:
    await FileSummaryStore(tmp_path).seed([_record("same-id", "tweet-2")])

    stats = await FileImportStore(tmp_path).import_summaries(
        [_item("same-id", "tweet-2")],
        strategy,
    )

    records = _all_records(tmp_path)
    assert stats.inserted == 0
    assert stats.skipped == expected_skipped
    assert stats.updated == expected_updated
    assert len(records) == 1
    assert records[0]["summary_text"] == expected_text


@pytest.mark.asyncio
async def test_imported_summary_time_remains_normalized_to_naive(tmp_path: Path) -> None:
    item = _item("new-id", "tweet-3")
    item["created_at"] = "2026-02-01T08:00:00+08:00"

    stats = await FileImportStore(tmp_path).import_summaries(
        [item],
        ConflictStrategy.skip,
    )

    assert stats.inserted == 1
    assert _all_records(tmp_path)[0]["created_at"] == "2026-02-01T00:00:00"
