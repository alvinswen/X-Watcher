"""CHG-058 摘要导入批量会话、统计与异常收尾回归。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure import file_summary_repository as repo_mod
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.sync.domain.models import ConflictStrategy
from src.sync.infrastructure import file_import_repository as import_mod
from src.sync.infrastructure.file_import_repository import FileImportStore

_YEAR = 2_026


def _record(summary_id: str, tweet_id: str, text: str = "摘要") -> SummaryRecord:
    # 固定注入时间：导入分片与归一断言不依赖真实时钟。
    when = datetime(_YEAR, 8, 1, tzinfo=UTC)
    return SummaryRecord(
        summary_id=summary_id,
        tweet_id=tweet_id,
        summary_text=text,
        translation_text=None,
        model_provider="test",
        model_name="model",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost_usd=0.0,
        cached=False,
        is_generated_summary=True,
        content_hash=f"hash-{summary_id}",
        created_at=when,
        updated_at=when,
    )


def _item(summary_id: str, tweet_id: str, text: str = "摘要") -> dict[str, Any]:
    return _record(summary_id, tweet_id, text).model_dump(mode="json", exclude={"updated_at"})


@pytest.mark.asyncio
async def test_import_batch_preserves_four_stats_logs_once_and_discards_locator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FileImportStore(tmp_path)
    await store.seed_summaries([_record("existing", "tweet-existing")])
    original_exists = store._summaries.summary_exists

    async def maybe_fail(summary_id: str) -> bool:
        if summary_id == "broken":
            raise OSError("lookup failed")
        return await original_exists(summary_id)

    monkeypatch.setattr(store._summaries, "summary_exists", maybe_fail)
    items = [
        _item("existing", "tweet-existing", "updated"),
        _item("duplicate-id", "tweet-existing"),
        _item("inserted", "tweet-new"),
        _item("broken", "tweet-broken"),
    ]

    with caplog.at_level(logging.INFO, logger=import_mod.__name__):
        stats = await store.import_summaries(items, ConflictStrategy.overwrite)

    assert (stats.inserted, stats.updated, stats.skipped, stats.errors) == (1, 1, 1, 1)
    assert caplog.text.count("导入摘要批量语义") == 1
    assert "段长=500 刷新次数=0 条数=4" in caplog.text
    assert "跳过重复摘要导入" in caplog.text
    assert "导入摘要查重失败" in caplog.text
    assert str(tmp_path) not in repo_mod._locator_cache


@pytest.mark.asyncio
async def test_import_refreshes_at_injected_segment_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    original_batch = FileSummaryStore.batch_session

    @asynccontextmanager
    async def small_batch(
        self: FileSummaryStore,
    ) -> AsyncIterator[repo_mod._BatchSession]:
        async with original_batch(self, segment_size=2) as session:
            yield session

    monkeypatch.setattr(FileSummaryStore, "batch_session", small_batch)
    with caplog.at_level(logging.INFO, logger=import_mod.__name__):
        stats = await FileImportStore(tmp_path).import_summaries(
            [_item(f"s-{index}", f"tweet-{index}") for index in range(3)],
            ConflictStrategy.skip,
        )

    assert stats.inserted == 3
    assert "段长=2 刷新次数=1 条数=3" in caplog.text
    assert str(tmp_path) not in repo_mod._locator_cache


@pytest.mark.asyncio
async def test_import_batch_discards_private_locator_when_write_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileImportStore(tmp_path)
    original_upsert = store._summaries.upsert_summary
    calls = 0

    async def fail_second(fields: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("write aborted")
        await original_upsert(fields)

    monkeypatch.setattr(store._summaries, "upsert_summary", fail_second)
    with pytest.raises(RuntimeError, match="write aborted"):
        await store.import_summaries(
            [_item(f"s-{index}", f"tweet-{index}") for index in range(3)],
            ConflictStrategy.skip,
        )

    assert calls == 2
    assert str(tmp_path) not in repo_mod._locator_cache
