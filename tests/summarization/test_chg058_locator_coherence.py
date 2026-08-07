"""CHG-058 摘要定位表丢弃、撞车源头拦与批量会话回归。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.storage.jsonl_store import read_shard, write_shard
from src.storage.paths import summary_shard
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure import file_summary_repository as repo_mod
from src.summarization.infrastructure.file_summary_repository import (
    FileSummaryStore,
    summary_write_progress,
)

_YEAR = 2_026


def _record(
    summary_id: str,
    tweet_id: str,
    *,
    text: str = "摘要",
    content_hash: str = "hash",
    month: int = 8,
) -> SummaryRecord:
    # 固定注入时间：目标月份不依赖真实时钟。
    when = datetime(_YEAR, month, 1, tzinfo=UTC)
    return SummaryRecord(
        summary_id=summary_id,
        tweet_id=tweet_id,
        summary_text=text,
        translation_text=f"译文-{text}",
        model_provider="test",
        model_name="model",
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
        cost_usd=0.5,
        cached=False,
        is_generated_summary=True,
        content_hash=content_hash,
        created_at=when,
        updated_at=when,
    )


def _prime_stale_locator(root: Path, existing: SummaryRecord) -> None:
    repo_mod._locator_cache.clear()
    locator = repo_mod._locator(root)
    target = summary_shard(root, existing.created_at)
    write_shard(target, [existing.model_dump(mode="json")])
    repo_mod._locator_cache[str(root)] = (repo_mod._shard_signature(root), locator)


@pytest.mark.asyncio
async def test_single_write_discards_locator_and_next_read_self_heals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileSummaryStore(tmp_path)
    await store.seed([_record("s-a", "1001", month=2)])
    original_write = repo_mod.write_shard
    injected = False

    def racing_write(path: Path, records: list[dict[str, object]]) -> None:
        nonlocal injected
        original_write(path, records)
        if not injected:
            injected = True
            other = _record("s-other", "1002", month=7)
            original_write(
                summary_shard(tmp_path, other.created_at),
                [other.model_dump(mode="json")],
            )

    monkeypatch.setattr(repo_mod, "write_shard", racing_write)
    await store.save_summary_record(_record("s-mine", "1003", month=3))

    assert str(tmp_path) not in repo_mod._locator_cache
    assert (await store.get_summary_by_tweet("1002")).summary_id == "s-other"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_collision_uses_double_key_overwrites_mutable_fields_and_logs_progress(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    existing = _record("s-theirs", "123456789012345", text="theirs", content_hash="same")
    _prime_stale_locator(tmp_path, existing)
    incoming = _record("s-mine", existing.tweet_id, text="mine", content_hash="same")

    with (
        caplog.at_level(logging.WARNING, logger=repo_mod.__name__),
        summary_write_progress(2, 3),
    ):
        returned = await FileSummaryStore(tmp_path).save_summary_record(incoming)

    records = read_shard(summary_shard(tmp_path, incoming.created_at))
    assert len(records) == 1
    assert returned.summary_id == "s-theirs"
    assert records[0]["summary_id"] == "s-theirs"
    assert records[0]["summary_text"] == "mine"
    assert records[0]["translation_text"] == "译文-mine"
    assert records[0]["updated_at"] != existing.updated_at.isoformat()
    assert f"month={_YEAR}-08" in caplog.text
    assert "progress=2/3" in caplog.text
    assert "tweet_id=123456789012345" in caplog.text
    assert "处置=已用本次内容覆盖既有那条" in caplog.text
    assert "theirs" not in caplog.text
    assert "译文-mine" not in caplog.text


@pytest.mark.asyncio
async def test_collision_requires_tweet_id_and_content_hash(tmp_path: Path) -> None:
    different_hash = tmp_path / "different"
    existing = _record("s-existing", "2001", content_hash="h1")
    _prime_stale_locator(different_hash, existing)
    await FileSummaryStore(different_hash).save_summary_record(
        _record("s-new", "2001", content_hash="h2")
    )
    assert len(read_shard(summary_shard(different_hash, existing.created_at))) == 2

    same_hash = tmp_path / "same"
    _prime_stale_locator(same_hash, existing)
    await FileSummaryStore(same_hash).save_summary_record(
        _record("s-new", "2001", content_hash="h1")
    )
    assert len(read_shard(summary_shard(same_hash, existing.created_at))) == 1


@pytest.mark.asyncio
async def test_batch_session_is_private_refreshes_by_segment_and_discards_on_exit(
    tmp_path: Path
) -> None:
    store = FileSummaryStore(tmp_path)
    await store.seed([])

    async with store.batch_session(segment_size=2) as session:
        assert str(tmp_path) not in repo_mod._locator_cache
        for index in range(3):
            record = _record(f"s-{index}", f"300{index}")
            await store.upsert_summary(record.model_dump(mode="json", exclude={"updated_at"}))
        assert session.refreshes == 1
        assert str(tmp_path) not in repo_mod._locator_cache

        reader = FileSummaryStore(tmp_path)
        assert await reader.get_summary_by_tweet("3002") is not None
        cached = repo_mod._locator_cache[str(tmp_path)][1]
        assert cached is not store._batch

    assert str(tmp_path) not in repo_mod._locator_cache

    with pytest.raises(RuntimeError, match="abort"):
        async with store.batch_session(segment_size=2):
            raise RuntimeError("abort")
    assert str(tmp_path) not in repo_mod._locator_cache
