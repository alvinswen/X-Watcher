"""CHG-029 by-day 启动重建时机、等价性与降级回归。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock

import pytest

from src.browse.infrastructure.file_browse_read_repository import FileBrowseReadStore
from src.feed.infrastructure.file_feed_read_repository import FileFeedReadStore
from src.main import app, lifespan
from src.mcp.server import mcp_lifespan
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.storage import paths, views


def _tweet(tweet_id: str, day: int) -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=f"tweet {tweet_id}",
        created_at=datetime(2026, 1, day, 12, tzinfo=UTC),
        author_username="alice",
    )


def _bytes_by_path(files: list[Path], root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in files}


def test_file_tweet_store_constructor_does_not_rebuild(monkeypatch, tmp_path: Path) -> None:
    rebuild = MagicMock(side_effect=AssertionError("constructor must not rebuild"))
    monkeypatch.setattr(views, "rebuild_by_day", rebuild)

    FileTweetStore(tmp_path)

    rebuild.assert_not_called()


@pytest.mark.asyncio
async def test_incremental_by_day_matches_full_rebuild_byte_for_byte(tmp_path: Path) -> None:
    store = FileTweetStore(tmp_path)
    await store.save_tweets([_tweet("t1", 1), _tweet("t2", 2), _tweet("t3", 2)], early_stop_threshold=0)
    incremental = _bytes_by_path(paths.iter_by_day_shards(tmp_path), tmp_path)

    views.rebuild_by_day(tmp_path)

    assert _bytes_by_path(paths.iter_by_day_shards(tmp_path), tmp_path) == incremental


@pytest.mark.asyncio
async def test_rebuild_leaves_canonical_shards_byte_identical(tmp_path: Path) -> None:
    store = FileTweetStore(tmp_path)
    await store.save_tweets([_tweet("t1", 1), _tweet("t2", 2)], early_stop_threshold=0)
    before = _bytes_by_path(paths.iter_canonical_shards(tmp_path), tmp_path)

    views.rebuild_by_day(tmp_path)

    assert _bytes_by_path(paths.iter_canonical_shards(tmp_path), tmp_path) == before


def test_warm_start_logs_error_with_traceback_and_continues(monkeypatch, tmp_path: Path, caplog) -> None:
    monkeypatch.setattr(views, "rebuild_by_day", MagicMock(side_effect=OSError("broken view")))

    with caplog.at_level(logging.ERROR, logger=views.__name__):
        assert views.warm_start_by_day(tmp_path) is None

    record = next(record for record in caplog.records if "重建 by-day" in record.message)
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_mcp_lifespan_continues_when_warm_start_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(views, "rebuild_by_day", MagicMock(side_effect=FileNotFoundError("racing rebuild")))

    async with mcp_lifespan(MagicMock()):
        pass


@pytest.mark.asyncio
async def test_rest_lifespan_invokes_warm_start(monkeypatch) -> None:
    warm_start = MagicMock()
    monkeypatch.setattr(views, "warm_start_by_day", warm_start)

    async with lifespan(app):
        pass

    warm_start.assert_called_once()


@pytest.mark.asyncio
async def test_failed_warm_start_degrades_browse_and_feed_to_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(views, "rebuild_by_day", MagicMock(side_effect=OSError("broken view")))
    views.warm_start_by_day(tmp_path)

    browse_items, browse_total = await FileBrowseReadStore(tmp_path).get_tweets(
        "2026-01-01", None, 1, 20
    )
    feed = await FileFeedReadStore(tmp_path).get_feed(
        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), 20
    )

    assert (browse_items, browse_total) == ([], 0)
    assert (feed.items, feed.total) == ([], 0)


@pytest.mark.asyncio
async def test_dual_cold_starts_end_with_complete_view(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = FileTweetStore(tmp_path)
    await store.save_tweets(
        [_tweet("t1", 1), _tweet("t2", 2), _tweet("t3", 3)],
        early_stop_threshold=0,
    )
    views.rebuild_by_day(tmp_path)
    paths.by_day_state_doc(tmp_path).unlink()

    first_write_started = Event()
    release_writes = Event()
    original_write = views.write_shard

    def delayed_write(path: Path, records: list[dict[str, object]]) -> None:
        first_write_started.set()
        release_writes.wait(timeout=5)
        original_write(path, records)

    monkeypatch.setattr(views, "write_shard", delayed_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(views.warm_start_by_day, tmp_path) for _ in range(2)]
        assert first_write_started.wait(timeout=5)
        visible_while_rebuilding = paths.iter_by_day_shards(tmp_path)
        release_writes.set()
        for future in futures:
            future.result()

    ok, detail = views.reconcile_by_day(tmp_path)
    assert visible_while_rebuilding
    assert ok is True
    assert detail["only_canonical"] == []
    assert detail["only_view"] == []
    # 双冷启结束后副本必须与正本完全一致（B-4 = A）。
