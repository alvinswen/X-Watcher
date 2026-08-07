"""CHG-042 摘要月分片、定位表与迁移就绪度回归。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import src.subjects.store as subject_store_module
import src.summarization.infrastructure.file_summary_repository as summary_module
from src.preference.domain.models import ScraperFollow, XUserProfile
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.preference.infrastructure.file_profile_repository import FileProfileStore
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.shared.read_cache import load_summary_map
from src.storage.doc_store import atomic_write_doc
from src.storage.index import TweetIdIndex
from src.storage.jsonl_store import read_shard, write_shard
from src.storage.paths import (
    iter_summary_shards,
    summary_legacy_doc,
    summary_shard,
)
from src.subjects.models import SubjectMatch
from src.subjects.store import FileSubjectStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.summarization.infrastructure.summary_store import RepositoryError
from src.user.infrastructure.file_user_repository import FileUserStore


def _summary(
    summary_id: str,
    tweet_id: str,
    created_at: datetime,
    *,
    content_hash: str = "shared-hash",
    text: str = "summary",
) -> SummaryRecord:
    return SummaryRecord(
        summary_id=summary_id,
        tweet_id=tweet_id,
        summary_text=text,
        translation_text=f"translation {text}",
        model_provider="test",
        model_name="test",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0,
        cached=False,
        is_generated_summary=True,
        content_hash=content_hash,
        created_at=created_at,
        updated_at=created_at,
    )


def _records_for_tweet(root: Path, tweet_id: str) -> list[dict[str, object]]:
    return [
        record
        for shard in iter_summary_shards(root)
        for record in read_shard(shard)
        if record["tweet_id"] == tweet_id
    ]


def _run_migration(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    repository_root = Path(__file__).parents[2]
    return subprocess.run(
        [
            sys.executable,
            "scripts/migrate_summaries_to_monthly_shards.py",
            "--data-root",
            str(root),
            *args,
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_legacy_summaries(root: Path, records: list[SummaryRecord]) -> bytes:
    legacy = summary_legacy_doc(root)
    atomic_write_doc(
        legacy,
        {"summaries": {record.summary_id: record.model_dump(mode="json") for record in records}},
    )
    return legacy.read_bytes()


def _run_duplicate_summary_runbook(root: Path) -> subprocess.CompletedProcess[str]:
    repository_root = Path(__file__).parents[2]
    operations = (repository_root / "OPERATIONS.md").read_text(encoding="utf-8")
    section = operations.split("## 同一推文多条摘要自查 runbook", maxsplit=1)[1]
    script = section.split("```bash", maxsplit=1)[1].split("```", maxsplit=1)[0]
    return subprocess.run(
        ["bash", "-c", script],
        cwd=repository_root.parents[1],
        env={**os.environ, "XWATCHER_DATA_ROOT": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_migration_defaults_to_dry_run_then_executes_a_to_d_and_archives(
    tmp_path: Path,
) -> None:
    records = [
        _summary("feb", "tweet-feb", datetime(2026, 2, 2, tzinfo=UTC)),
        _summary("jul", "tweet-jul", datetime(2026, 7, 2, tzinfo=UTC)),
    ]
    legacy_bytes = _write_legacy_summaries(tmp_path, records)

    dry_run = _run_migration(tmp_path)
    assert dry_run.returncode == 0, dry_run.stderr
    assert "DRY-RUN" in dry_run.stdout
    assert "已处理 2 / 总数 2" in dry_run.stdout
    assert summary_legacy_doc(tmp_path).read_bytes() == legacy_bytes
    assert iter_summary_shards(tmp_path) == []

    executed = _run_migration(tmp_path, "--execute")
    assert executed.returncode == 0, executed.stderr
    assert "A-C 核对通过" in executed.stdout
    assert "D 核对通过" in executed.stdout
    assert [path.name for path in iter_summary_shards(tmp_path)] == [
        "2026-02.jsonl",
        "2026-07.jsonl",
    ]
    assert not summary_legacy_doc(tmp_path).exists()
    archives = list((tmp_path / "summaries").glob("summaries.json.migrated-*"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == legacy_bytes
    migrated = {
        record["summary_id"]: record
        for shard in iter_summary_shards(tmp_path)
        for record in read_shard(shard)
    }
    assert migrated == {record.summary_id: record.model_dump(mode="json") for record in records}


def test_migration_refuses_existing_shards_unless_forced(tmp_path: Path) -> None:
    record = _summary("only", "tweet-only", datetime(2026, 4, 2, tzinfo=UTC))
    _write_legacy_summaries(tmp_path, [record])
    shard = summary_shard(tmp_path, record.created_at)
    write_shard(shard, [{"summary_id": "stale"}])

    refused = _run_migration(tmp_path, "--execute")
    assert refused.returncode == 1
    assert "已存在月分片" in refused.stderr
    assert summary_legacy_doc(tmp_path).exists()
    assert read_shard(shard) == [{"summary_id": "stale"}]

    forced = _run_migration(tmp_path, "--execute", "--force")
    assert forced.returncode == 0, forced.stderr
    assert read_shard(shard) == [record.model_dump(mode="json")]
    assert not summary_legacy_doc(tmp_path).exists()


@pytest.mark.asyncio
async def test_duplicate_summary_runbook_reports_and_clears_residual_race(
    tmp_path: Path,
) -> None:
    older = _summary(
        "older-summary",
        "duplicate-tweet",
        datetime(2026, 2, 1, tzinfo=UTC),
    )
    newer = _summary(
        "newer-summary",
        "duplicate-tweet",
        datetime(2026, 7, 1, tzinfo=UTC),
    )
    older_shard = summary_shard(tmp_path, older.created_at)
    newer_shard = summary_shard(tmp_path, newer.created_at)
    write_shard(older_shard, [older.model_dump(mode="json")])
    write_shard(newer_shard, [newer.model_dump(mode="json")])

    with pytest.raises(RepositoryError, match="多条记录匹配"):
        await FileSummaryStore(tmp_path).get_summary_by_tweet("duplicate-tweet")

    duplicate = _run_duplicate_summary_runbook(tmp_path)
    assert duplicate.returncode == 1
    assert "tweet_id=duplicate-tweet" in duplicate.stdout
    assert "删除 分片=2026-02.jsonl summary_id=older-summary" in duplicate.stdout
    assert "保留 分片=2026-07.jsonl summary_id=newer-summary" in duplicate.stdout

    write_shard(older_shard, [])
    repaired = _run_duplicate_summary_runbook(tmp_path)
    assert repaired.returncode == 0
    assert "OK: 未发现同一 tweet_id 的多条摘要" in repaired.stdout


@pytest.mark.asyncio
async def test_seed_replaces_existing_shards_and_groups_by_created_month(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    await store.seed(
        [
            _summary("old-1", "old-t1", datetime(2026, 2, 1, tzinfo=UTC)),
            _summary("old-2", "old-t2", datetime(2026, 7, 1, tzinfo=UTC)),
        ]
    )

    replacement = [
        _summary("new-1", "new-t1", datetime(2026, 3, 1, tzinfo=UTC)),
        _summary("new-2", "new-t2", datetime(2026, 3, 2, tzinfo=UTC)),
        _summary("new-3", "new-t3", datetime(2026, 5, 1, tzinfo=UTC)),
        _summary("new-4", "new-t4", datetime(2026, 5, 2, tzinfo=UTC)),
    ]
    await store.seed(replacement)

    assert [path.name for path in iter_summary_shards(tmp_path)] == [
        "2026-03.jsonl",
        "2026-05.jsonl",
    ]
    assert [len(read_shard(path)) for path in iter_summary_shards(tmp_path)] == [2, 2]
    assert await store.get_all_summaries() == replacement


@pytest.mark.asyncio
async def test_save_updates_cross_month_match_in_original_shard(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    original = _summary(
        "original-id",
        "tweet-1",
        datetime(2026, 2, 10, tzinfo=UTC),
        text="before",
    )
    await store.seed([original])

    incoming = _summary(
        "incoming-id",
        "tweet-1",
        datetime(2026, 7, 10, tzinfo=UTC),
        text="after",
    )
    saved = await store.save_summary_record(incoming)

    records = _records_for_tweet(tmp_path, "tweet-1")
    assert len(records) == 1
    assert records[0]["summary_id"] == original.summary_id
    assert records[0]["created_at"] == original.model_dump(mode="json")["created_at"]
    assert records[0]["summary_text"] == "after"
    assert datetime.fromisoformat(str(records[0]["updated_at"])).tzinfo is not None
    assert summary_shard(tmp_path, original.created_at).exists()
    assert not summary_shard(tmp_path, incoming.created_at).exists()
    assert saved.summary_id == original.summary_id
    assert saved.created_at == incoming.created_at


@pytest.mark.asyncio
async def test_user_and_api_key_new_times_are_utc_aware(tmp_path: Path) -> None:
    store = FileUserStore(tmp_path)
    user = await store.create_user("UTC user", "utc@example.com", "hash")
    key = await store.create_api_key(user.id, "key-hash", "prefix")
    await store.update_key_last_used(key.id)

    doc = json.loads((tmp_path / "users" / "users.json").read_text(encoding="utf-8"))
    stored_user = doc["users"][str(user.id)]
    stored_key = doc["api_keys"][str(key.id)]
    assert datetime.fromisoformat(stored_user["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(stored_key["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(stored_key["last_used_at"]).tzinfo is not None


@pytest.mark.asyncio
async def test_follows_and_profiles_mixed_naive_aware_sorting_stays_locked(
    tmp_path: Path,
) -> None:
    follow_store = FileFollowStore(tmp_path)
    await follow_store.seed(
        [
            ScraperFollow(
                id=1,
                username="naive-follow",
                added_at=datetime(2026, 1, 1),
                reason="test",
                added_by="test",
                is_active=True,
            ),
            ScraperFollow(
                id=2,
                username="aware-follow",
                added_at=datetime(2026, 1, 2, tzinfo=UTC),
                reason="test",
                added_by="test",
                is_active=True,
            ),
        ]
    )
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        await follow_store.get_all_follows()

    profile_store = FileProfileStore(tmp_path)
    await profile_store.seed(
        [
            XUserProfile(
                platform_user_id="naive-profile",
                username="naive-profile",
                fetched_at=datetime(2026, 1, 1),
            ),
            XUserProfile(
                platform_user_id="aware-profile",
                username="aware-profile",
                fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
        ]
    )
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        await profile_store.get_all_profiles()


@pytest.mark.asyncio
async def test_save_multiple_candidates_uses_created_at_string_max(tmp_path: Path) -> None:
    older = _summary(
        "older",
        "tweet-duplicate",
        datetime(2026, 3, 1, tzinfo=UTC),
        text="older untouched",
    )
    newer = _summary(
        "newer",
        "tweet-duplicate",
        datetime(2026, 6, 1, tzinfo=UTC),
        text="newer before",
    )
    write_shard(summary_shard(tmp_path, older.created_at), [older.model_dump(mode="json")])
    write_shard(summary_shard(tmp_path, newer.created_at), [newer.model_dump(mode="json")])

    await FileSummaryStore(tmp_path).save_summary_record(
        _summary(
            "third",
            "tweet-duplicate",
            datetime(2026, 7, 1, tzinfo=UTC),
            text="newer after",
        )
    )

    older_after = read_shard(summary_shard(tmp_path, older.created_at))[0]
    newer_after = read_shard(summary_shard(tmp_path, newer.created_at))[0]
    assert older_after == older.model_dump(mode="json")
    assert newer_after["summary_id"] == "newer"
    assert newer_after["summary_text"] == "newer after"
    assert len(_records_for_tweet(tmp_path, "tweet-duplicate")) == 2


@pytest.mark.asyncio
async def test_same_tweet_with_different_content_hash_remains_distinct(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    await store.save_summary_record(
        _summary(
            "first",
            "tweet-2",
            datetime(2026, 2, 1, tzinfo=UTC),
            content_hash="hash-a",
        )
    )
    await store.save_summary_record(
        _summary(
            "second",
            "tweet-2",
            datetime(2026, 7, 1, tzinfo=UTC),
            content_hash="hash-b",
        )
    )

    assert len(_records_for_tweet(tmp_path, "tweet-2")) == 2
    with pytest.raises(RepositoryError, match="多条记录匹配"):
        await store.get_summary_by_tweet("tweet-2")


@pytest.mark.asyncio
async def test_upsert_cross_month_removes_old_shard_record_first(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    original = _summary("same-id", "tweet-3", datetime(2026, 4, 1, tzinfo=UTC))
    await store.seed([original])
    fields = _summary(
        "same-id",
        "tweet-3",
        datetime(2026, 7, 1, tzinfo=UTC),
        text="moved",
    ).model_dump(mode="json", exclude={"updated_at"})

    await store.upsert_summary(fields)

    assert read_shard(summary_shard(tmp_path, original.created_at)) == []
    moved = read_shard(summary_shard(tmp_path, datetime(2026, 7, 1, tzinfo=UTC)))
    assert len(moved) == 1
    assert moved[0]["summary_id"] == "same-id"
    assert moved[0]["summary_text"] == "moved"
    assert sum(
        record["summary_id"] == "same-id"
        for shard in iter_summary_shards(tmp_path)
        for record in read_shard(shard)
    ) == 1


@pytest.mark.asyncio
async def test_locator_rebuilds_after_external_shard_write(tmp_path: Path) -> None:
    store = FileSummaryStore(tmp_path)
    first = _summary("first", "tweet-first", datetime(2026, 2, 1, tzinfo=UTC))
    await store.seed([first])
    assert await store.get_summary_by_tweet("tweet-first") == first

    second = _summary("second", "tweet-second", datetime(2026, 7, 1, tzinfo=UTC))
    write_shard(summary_shard(tmp_path, second.created_at), [second.model_dump(mode="json")])

    assert await store.get_summary_by_tweet("tweet-second") == second
    assert not any("locator" in path.name or "index" in path.name for path in tmp_path.rglob("*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_mode", ["missing", "empty"])
async def test_new_empty_instance_returns_empty_without_error(
    tmp_path: Path,
    legacy_mode: str,
) -> None:
    root = tmp_path / legacy_mode
    if legacy_mode == "empty":
        atomic_write_doc(summary_legacy_doc(root), {"summaries": {}})
        assert summary_legacy_doc(root).stat().st_size > 0

    assert await FileSummaryStore(root).get_all_summaries() == []
    assert await load_summary_map(root) == {}


@pytest.mark.asyncio
async def test_unmigrated_nonempty_legacy_file_fails_loudly(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "unmigrated"
    legacy_record = _summary("legacy", "legacy-tweet", datetime(2026, 2, 1, tzinfo=UTC))
    atomic_write_doc(
        summary_legacy_doc(root),
        {"summaries": {legacy_record.summary_id: legacy_record.model_dump(mode="json")}},
    )

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(RepositoryError, match="尚未迁移的历史摘要数据"),
    ):
        await FileSummaryStore(root).get_all_summaries()
    with pytest.raises(RepositoryError, match="尚未迁移的历史摘要数据"):
        await load_summary_map(root)

    assert str(root) in caplog.text
    assert str(summary_legacy_doc(root)) in caplog.text


@pytest.mark.asyncio
async def test_nonempty_legacy_file_is_allowed_when_shards_exist(tmp_path: Path) -> None:
    record = _summary("ready", "ready-tweet", datetime(2026, 3, 1, tzinfo=UTC))
    atomic_write_doc(
        summary_legacy_doc(tmp_path),
        {"summaries": {"legacy-copy": record.model_dump(mode="json")}},
    )
    write_shard(summary_shard(tmp_path, record.created_at), [record.model_dump(mode="json")])

    assert await FileSummaryStore(tmp_path).get_all_summaries() == [record]
    assert (await load_summary_map(tmp_path))[record.tweet_id] == record


@pytest.mark.asyncio
async def test_mcp_save_summaries_uses_real_monthly_store_and_rebuilds_locator_per_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    existing_hash = hashlib.sha256(b"existing-tweet:claude_code").hexdigest()
    existing = _summary(
        "existing-id",
        "existing-tweet",
        datetime(2026, 2, 1, tzinfo=UTC),
        content_hash=existing_hash,
        text="before",
    )
    await FileSummaryStore(tmp_path).seed([existing])
    # CHG-046: save_summaries 存在性 fail-closed——两条 tweet_id 需先在推文库
    await FileTweetStore(tmp_path).save_tweets(
        [
            Tweet(
                tweet_id=tid,
                text="测试推文",
                author_username="alice",
                created_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
            for tid in ("existing-tweet", "new-tweet")
        ],
        early_stop_threshold=0,
    )

    build_calls = 0
    original_build = summary_module._build_locator

    def counted_build(shards: list[Path]) -> summary_module._Locator:
        nonlocal build_calls
        build_calls += 1
        return original_build(shards)

    monkeypatch.setattr(summary_module, "_build_locator", counted_build)

    from src.mcp.server import create_mcp_server

    tools = create_mcp_server()._tool_manager._tools
    save_summaries = tools["save_summaries"].fn
    with (
        patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
        patch("src.mcp.security.audit_log"),
    ):
        result = json.loads(
            await save_summaries(
                summaries=[
                    {"tweet_id": "existing-tweet", "summary": "after"},
                    {"tweet_id": "new-tweet", "summary": "new summary"},
                ]
            )
        )

    assert result["success"] is True
    assert result["data"]["saved"] == 2
    # Agent 回写若将来改成批量化，本断言会再次变红：那是预期语义变化，不是回归。
    assert build_calls == 2
    existing_records = _records_for_tweet(tmp_path, "existing-tweet")
    new_records = _records_for_tweet(tmp_path, "new-tweet")
    assert len(existing_records) == 1
    assert existing_records[0]["summary_id"] == "existing-id"
    assert existing_records[0]["summary_text"] == "after"
    assert len(new_records) == 1
    assert [path.name for path in iter_summary_shards(tmp_path)] == [
        "2026-02.jsonl",
        datetime.now(UTC).strftime("%Y-%m") + ".jsonl",
    ]


@pytest.mark.asyncio
async def test_tweet_index_is_lazy_for_constructor_and_pure_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_calls = 0
    original_build = TweetIdIndex.build

    def counted_build(data_root: Path) -> TweetIdIndex:
        nonlocal build_calls
        build_calls += 1
        return original_build(data_root)

    monkeypatch.setattr(TweetIdIndex, "build", staticmethod(counted_build))
    store = FileTweetStore(tmp_path)

    assert await store.get_all_tweets() == []
    assert build_calls == 0
    assert await store.tweet_exists("missing") is False
    assert build_calls == 1


@pytest.mark.asyncio
async def test_tweet_save_builds_index_once_and_two_instances_share_disk_visibility(
    tmp_path: Path,
) -> None:
    first = FileTweetStore(tmp_path)
    second = FileTweetStore(tmp_path)
    tweet = Tweet(
        tweet_id="tweet-from-second",
        text="stored by second instance",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        author_username="alice",
    )

    result = await second.save_tweets([tweet], early_stop_threshold=0)

    assert result.success_count == 1
    assert await first.tweet_exists(tweet.tweet_id) is True


@pytest.mark.asyncio
async def test_subject_matches_touch_once_with_latest_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSubjectStore(tmp_path)
    subject = await store.create_subject(name="subject", nl_description="description")
    early = datetime(2026, 5, 1, tzinfo=UTC)
    middle = datetime(2026, 5, 2, tzinfo=UTC)
    late = datetime(2026, 5, 3, tzinfo=UTC)
    touch_calls: list[tuple[str, datetime | None]] = []
    original_touch = store.touch_subject

    async def counted_touch(subject_id: str, when: datetime | None = None) -> None:
        touch_calls.append((subject_id, when))
        await original_touch(subject_id, when)

    monkeypatch.setattr(store, "touch_subject", counted_touch)

    await store.upsert_matches(
        [
            SubjectMatch(subject_id=subject.subject_id, tweet_id="late", matched_at=late),
            SubjectMatch(subject_id=subject.subject_id, tweet_id="early", matched_at=early),
            SubjectMatch(subject_id=subject.subject_id, tweet_id="middle", matched_at=middle),
        ]
    )

    assert touch_calls == [(subject.subject_id, late)]
    updated = await store.get_subject(subject.subject_id)
    assert updated is not None
    assert updated.last_updated_at == late


@pytest.mark.asyncio
async def test_subject_empty_match_batch_does_not_touch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSubjectStore(tmp_path)
    subject = await store.create_subject(name="subject", nl_description="description")
    touch_calls = 0

    async def counted_touch(subject_id: str, when: datetime | None = None) -> None:  # noqa: ARG001
        nonlocal touch_calls
        touch_calls += 1

    monkeypatch.setattr(store, "touch_subject", counted_touch)

    saved = await store.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="irrelevant",
                matched_at=datetime(2026, 5, 1, tzinfo=UTC),
                relevant=False,
            )
        ]
    )

    assert saved == []
    assert touch_calls == 0


@pytest.mark.asyncio
async def test_subject_partial_shard_failure_does_not_refresh_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSubjectStore(tmp_path)
    subject = await store.create_subject(name="subject", nl_description="description")
    original_upsert = subject_store_module.upsert

    def fail_second_month(
        path: Path,
        records: list[dict[str, object]],
        key: str = "tweet_id",
    ) -> int:
        if path.name == "2026-06.jsonl":
            raise OSError("injected second shard failure")
        return original_upsert(path, records, key)

    monkeypatch.setattr(subject_store_module, "upsert", fail_second_month)

    with pytest.raises(OSError, match="injected second shard failure"):
        await store.upsert_matches(
            [
                SubjectMatch(
                    subject_id=subject.subject_id,
                    tweet_id="may",
                    matched_at=datetime(2026, 5, 1, tzinfo=UTC),
                ),
                SubjectMatch(
                    subject_id=subject.subject_id,
                    tweet_id="june",
                    matched_at=datetime(2026, 6, 1, tzinfo=UTC),
                ),
            ]
        )

    assert read_shard(
        tmp_path / "subjects" / subject.subject_id / "matches" / "2026-05.jsonl"
    )
    unchanged = await store.get_subject(subject.subject_id)
    assert unchanged is not None
    assert unchanged.last_updated_at is None
