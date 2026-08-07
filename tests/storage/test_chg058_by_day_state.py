"""CHG-058 by-day 双指纹现场记录与强制重建回归。"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.storage import paths, views
from src.storage.doc_store import atomic_write_doc, read_doc
from src.storage.jsonl_store import read_shard, write_shard

_YEAR = 2_026


def _tweet(tweet_id: str, text: str = "正文") -> dict[str, object]:
    # 固定注入时间：避免真实时钟参与分片选择。
    created_at = datetime(_YEAR, 8, 1, 12, tzinfo=UTC)
    return {
        "tweet_id": tweet_id,
        "text": text,
        "created_at": created_at.isoformat(),
        "author_username": "alice",
    }


def _seed(root: Path, records: list[dict[str, object]] | None = None) -> Path:
    created_at = datetime(_YEAR, 8, 1, 12, tzinfo=UTC)
    shard = paths.canonical_shard(root, "alice", created_at)
    write_shard(shard, records or [_tweet("t1")])
    return shard


def test_state_records_both_fingerprints_and_all_skip_reasons(tmp_path: Path) -> None:
    canonical = _seed(tmp_path)
    assert views._skip_reason(tmp_path) == "现场记录缺失"

    stats = views.rebuild_by_day(tmp_path)
    state = paths.by_day_state_doc(tmp_path)
    assert stats == {"days": 1, "stale": 0}
    assert state.exists()
    assert state not in paths.iter_by_day_shards(tmp_path)
    assert views._skip_reason(tmp_path) is None

    write_shard(canonical, [*_seed_records(canonical), _tweet("t2")])
    assert views._skip_reason(tmp_path) == "推文正本变了"

    views.rebuild_by_day(tmp_path)
    write_shard(paths.iter_by_day_shards(tmp_path)[0], [])
    assert views._skip_reason(tmp_path) == "按天索引副本被改动"

    views.rebuild_by_day(tmp_path)
    state.unlink()
    assert views._skip_reason(tmp_path) == "现场记录缺失"
    state.write_text("{坏掉", encoding="utf-8")
    assert views._skip_reason(tmp_path) == "现场记录读不出"


def _seed_records(shard: Path) -> list[dict[str, object]]:
    return read_shard(shard)


@pytest.mark.parametrize("version", [0, 2, None])
def test_unknown_or_missing_state_version_forces_rebuild(
    tmp_path: Path, version: int | None
) -> None:
    _seed(tmp_path)
    views.rebuild_by_day(tmp_path)
    state = paths.by_day_state_doc(tmp_path)
    doc = read_doc(state)
    assert doc is not None
    if version is None:
        doc.pop("version")
    else:
        doc["version"] = version
    atomic_write_doc(state, doc)

    assert views._skip_reason(tmp_path) == "现场记录版本不认识"


def test_malformed_fingerprint_and_state_write_failure_degrade_to_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _seed(tmp_path)
    views.rebuild_by_day(tmp_path)
    state = paths.by_day_state_doc(tmp_path)
    doc = read_doc(state)
    assert doc is not None
    doc["canonical"] = [["missing-fields"]]
    atomic_write_doc(state, doc)
    assert views._skip_reason(tmp_path) == "现场记录读不出"

    state.unlink()

    def fail_write(_path: Path, _doc: dict[str, object]) -> None:
        raise OSError("state is read-only")

    monkeypatch.setattr(views, "atomic_write_doc", fail_write)
    with caplog.at_level("WARNING", logger=views.__name__):
        assert views.rebuild_by_day(tmp_path)["days"] == 1
    assert not state.exists()
    assert "下次启动会多重建一次" in caplog.text


def test_same_mtime_and_size_blind_spot_is_repaired_by_forced_rebuild(tmp_path: Path) -> None:
    canonical = _seed(tmp_path, [_tweet("t1", "before")])
    views.rebuild_by_day(tmp_path)
    before = canonical.stat()

    write_shard(canonical, [_tweet("t1", "after!")])
    assert canonical.stat().st_size == before.st_size
    os.utime(canonical, ns=(before.st_atime_ns, before.st_mtime_ns))

    assert views._skip_reason(tmp_path) is None
    assert views.reconcile_by_day(tmp_path)[0] is False
    views.rebuild_by_day(tmp_path)
    assert views.reconcile_by_day(tmp_path)[0] is True


def test_rebuild_removes_invalid_jsonl_ghost_but_preserves_state(tmp_path: Path) -> None:
    _seed(tmp_path)
    views.rebuild_by_day(tmp_path)
    ghost = paths.by_day_dir(tmp_path) / "not-a-date.jsonl"
    write_shard(ghost, [_tweet("ghost")])

    assert views.rebuild_by_day(tmp_path) == {"days": 1, "stale": 1}
    assert not ghost.exists()
    assert paths.by_day_state_doc(tmp_path).exists()
    assert paths.by_day_shard(tmp_path, date(_YEAR, 8, 1)).exists()
