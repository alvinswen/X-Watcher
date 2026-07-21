"""JSONL storage primitive tests."""

import logging

from src.storage import jsonl_store as jsonl_store_module
from src.storage.jsonl_store import append, read_shard, upsert, write_shard


def test_read_shard_returns_empty_for_missing_file(tmp_path):
    assert read_shard(tmp_path / "missing.jsonl") == []


def test_read_shard_skips_blank_lines(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text("\n  \n", encoding="utf-8")

    assert read_shard(path) == []


def test_read_shard_skips_malformed_lines(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"tweet_id":"1"}\nnot-json\n', encoding="utf-8")

    assert read_shard(path) == [{"tweet_id": "1"}]


def test_read_shard_reports_malformed_lines_once_per_file(tmp_path, caplog):
    path = tmp_path / "records.jsonl"
    path.write_text(
        (
            '{"tweet_id":"1"}\nnot-json\n{"tweet_id":"2"}\n{bad\n'
            '{"tweet_id":"3"}\nnope\n{"tweet_id":"4"}\n{"tweet_id":"5"}\n'
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        records = read_shard(path)

    assert records == [
        {"tweet_id": "1"},
        {"tweet_id": "2"},
        {"tweet_id": "3"},
        {"tweet_id": "4"},
        {"tweet_id": "5"},
    ]
    assert len(caplog.records) == 1
    assert caplog.records[0].name == jsonl_store_module.__name__
    assert str(path) in caplog.records[0].getMessage()
    assert "3 条坏行" in caplog.records[0].getMessage()


def test_read_shard_valid_and_blank_lines_do_not_warn(tmp_path, caplog):
    path = tmp_path / "records.jsonl"
    path.write_text('{"tweet_id":"1"}\n\n', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        records = read_shard(path)

    assert records == [{"tweet_id": "1"}]
    assert caplog.records == []


def test_write_shard_round_trips_records(tmp_path):
    path = tmp_path / "records.jsonl"
    records = [
        {"tweet_id": "1", "text": "中文"},
        {"tweet_id": "2", "text": "second"},
    ]

    write_shard(path, records)

    assert read_shard(path) == records


def test_append_accumulates_records(tmp_path):
    path = tmp_path / "records.jsonl"

    append(path, {"tweet_id": "1"})
    append(path, {"tweet_id": "2"})

    assert read_shard(path) == [{"tweet_id": "1"}, {"tweet_id": "2"}]


def test_upsert_counts_new_default_keys(tmp_path):
    path = tmp_path / "records.jsonl"

    added = upsert(path, [{"tweet_id": "1"}, {"tweet_id": "2"}])

    assert added == 2
    assert read_shard(path) == [{"tweet_id": "1"}, {"tweet_id": "2"}]


def test_upsert_same_key_updates_without_incrementing(tmp_path):
    path = tmp_path / "records.jsonl"
    write_shard(path, [{"tweet_id": "1", "text": "old"}])

    added = upsert(path, [{"tweet_id": "1", "text": "new"}])

    assert added == 0
    assert read_shard(path) == [{"tweet_id": "1", "text": "new"}]


def test_upsert_mixed_batch_counts_only_new_keys(tmp_path):
    path = tmp_path / "records.jsonl"
    write_shard(path, [{"tweet_id": "1", "text": "old"}])

    added = upsert(
        path,
        [
            {"tweet_id": "1", "text": "updated"},
            {"tweet_id": "2", "text": "new"},
        ],
    )

    assert added == 1
    assert {record["tweet_id"]: record["text"] for record in read_shard(path)} == {
        "1": "updated",
        "2": "new",
    }
