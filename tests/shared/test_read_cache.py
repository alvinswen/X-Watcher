"""CHG-029 文件读缓存签名、隔离与只读消费回归。"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.browse.infrastructure.file_browse_read_repository import FileBrowseReadStore
from src.feed.infrastructure.file_feed_read_repository import FileFeedReadStore
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.search.infrastructure.file_search_read_repository import FileSearchReadStore
from src.shared.read_cache import load_all_tweets_map, load_summary_map
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore


def _summary(tweet_id: str, text: str) -> SummaryRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SummaryRecord(
        summary_id=f"summary-{tweet_id}",
        tweet_id=tweet_id,
        summary_text=text,
        translation_text=f"translation {text}",
        model_provider="test",
        model_name="test",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0,
        content_hash=f"hash-{tweet_id}",
        created_at=now,
        updated_at=now,
    )


def _tweet(tweet_id: str, author: str = "alice") -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=f"tweet {tweet_id}",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        author_username=author,
        author_user_id=f"user-{author}",
    )


@pytest.mark.asyncio
async def test_missing_summary_file_returns_stable_empty_map(tmp_path: Path) -> None:
    first = await load_summary_map(tmp_path)
    second = await load_summary_map(tmp_path)

    assert first == {}
    assert second is first


@pytest.mark.asyncio
async def test_summary_write_is_visible_on_next_read(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    await store.seed([_summary("t1", "before")])
    before = await load_summary_map(tmp_path)

    await store.seed([_summary("t1", "after with a different size")])
    after = await load_summary_map(tmp_path)

    assert before["t1"].summary_text == "before"
    assert after["t1"].summary_text == "after with a different size"
    assert after is not before


@pytest.mark.asyncio
async def test_summary_cache_is_isolated_by_data_root(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    await FileSummaryStore(root_a).seed([_summary("t1", "root-a")])
    await FileSummaryStore(root_b).seed([_summary("t1", "root-b")])

    cached_a = await load_summary_map(root_a)
    cached_b = await load_summary_map(root_b)

    assert cached_a["t1"].summary_text == "root-a"
    assert cached_b["t1"].summary_text == "root-b"
    assert cached_a is not cached_b


@pytest.mark.asyncio
async def test_same_mtime_and_size_is_documented_signature_blind_spot(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    await store.seed([_summary("t1", "alpha")])
    cached = await load_summary_map(tmp_path)
    summary_path = tmp_path / "summaries" / "summaries.json"
    original_stat = summary_path.stat()
    changed_bytes = summary_path.read_bytes().replace(b"alpha", b"bravo")
    assert len(changed_bytes) == original_stat.st_size
    summary_path.write_bytes(changed_bytes)
    os.utime(summary_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    stale = await load_summary_map(tmp_path)
    assert stale is cached
    assert stale["t1"].summary_text == "alpha"

    os.utime(summary_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1))
    refreshed = await load_summary_map(tmp_path)
    assert refreshed["t1"].summary_text == "bravo"


@pytest.mark.asyncio
async def test_browse_feed_search_share_map_without_pollution(tmp_path: Path) -> None:
    await FileSummaryStore(tmp_path).seed([_summary("t1", "shared")])
    cached = await load_summary_map(tmp_path)
    before = dict(cached)

    maps = [
        await FileBrowseReadStore(tmp_path)._build_summary_map(),
        await FileFeedReadStore(tmp_path)._build_summary_map(),
        await FileSearchReadStore(tmp_path)._build_summary_map(),
    ]

    assert all(mapping is cached for mapping in maps)
    assert cached == before


@pytest.mark.asyncio
async def test_tweet_write_is_visible_on_next_read(tmp_path: Path) -> None:
    store = FileTweetStore(tmp_path)
    await store.save_tweets([_tweet("t1")], early_stop_threshold=0)
    before = await load_all_tweets_map(tmp_path)

    await store.save_tweets([_tweet("t2")], early_stop_threshold=0)
    after = await load_all_tweets_map(tmp_path)

    assert set(before) == {"t1"}
    assert set(after) == {"t1", "t2"}
    assert after is not before


@pytest.mark.asyncio
async def test_tweet_cache_is_isolated_by_data_root(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    await FileTweetStore(root_a).save_tweets([_tweet("t1", "alice")], early_stop_threshold=0)
    await FileTweetStore(root_b).save_tweets([_tweet("t1", "bob")], early_stop_threshold=0)

    cached_a = await load_all_tweets_map(root_a)
    cached_b = await load_all_tweets_map(root_b)

    assert cached_a["t1"].author_username == "alice"
    assert cached_b["t1"].author_username == "bob"
    assert cached_a is not cached_b


@pytest.mark.asyncio
async def test_repeated_tweet_reads_return_unpolluted_shared_map(tmp_path: Path) -> None:
    await FileTweetStore(tmp_path).save_tweets([_tweet("t1")], early_stop_threshold=0)
    cached = await load_all_tweets_map(tmp_path)
    before = dict(cached)

    repeated = await load_all_tweets_map(tmp_path)

    assert repeated is cached
    assert repeated == before
