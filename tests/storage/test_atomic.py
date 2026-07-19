"""Atomic storage primitive tests."""

import asyncio

import pytest

import src.storage.atomic as atomic_module
from src.storage.atomic import atomic_replace, shard_lock


def test_atomic_replace_writes_bytes(tmp_path):
    path = tmp_path / "data.bin"

    atomic_replace(path, b"payload")

    assert path.read_bytes() == b"payload"


def test_atomic_replace_overwrites_existing_file(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"old")

    atomic_replace(path, b"new")

    assert path.read_bytes() == b"new"


def test_atomic_replace_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "data.bin"

    atomic_replace(path, b"payload")

    assert path.read_bytes() == b"payload"


def test_atomic_replace_interruption_preserves_old_target(tmp_path, monkeypatch):
    path = tmp_path / "data.bin"
    path.write_bytes(b"old")

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(atomic_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        atomic_replace(path, b"new")

    assert path.read_bytes() == b"old"


def test_shard_lock_returns_same_lock_for_same_path(tmp_path):
    path = tmp_path / "shard.jsonl"
    first = shard_lock(path)
    second = shard_lock(path)

    assert first is second


def test_shard_lock_returns_distinct_locks_for_distinct_paths(tmp_path):
    first = shard_lock(tmp_path / "first.jsonl")
    second = shard_lock(tmp_path / "second.jsonl")

    assert first is not second


@pytest.mark.asyncio
async def test_shard_lock_serializes_two_coroutines(tmp_path):
    path = tmp_path / "shard.jsonl"
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    events = []

    async def first_worker():
        async with shard_lock(path):
            events.append("first-enter")
            first_entered.set()
            await release_first.wait()
            events.append("first-exit")

    async def second_worker():
        await first_entered.wait()
        async with shard_lock(path):
            events.append("second-enter")

    first_task = asyncio.create_task(first_worker())
    await first_entered.wait()
    second_task = asyncio.create_task(second_worker())
    await asyncio.sleep(0)

    assert events == ["first-enter"]

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert events == ["first-enter", "first-exit", "second-enter"]
