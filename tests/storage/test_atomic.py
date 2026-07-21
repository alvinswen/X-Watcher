"""Atomic storage primitive tests."""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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


def test_atomic_replace_uses_process_unique_tmp_suffix_before_replace(tmp_path, monkeypatch):
    path = tmp_path / "data.bin"
    observed_tmp = None

    def capture_replace(source, destination):
        nonlocal observed_tmp
        observed_tmp = source
        assert destination == path
        assert source.read_bytes() == b"payload"

    monkeypatch.setattr(atomic_module.os, "replace", capture_replace)

    atomic_replace(path, b"payload")

    assert observed_tmp is not None
    assert re.fullmatch(r"data\.bin\.\d+\.[0-9a-f]{32}\.tmp", observed_tmp.name)


def test_atomic_replace_concurrent_writers_use_distinct_tmp_files(tmp_path, monkeypatch):
    path = tmp_path / "data.bin"
    barrier = Barrier(2)
    original_replace = atomic_module.os.replace
    observed_sources = []

    def synchronized_replace(source, destination):
        observed_sources.append(source)
        barrier.wait()
        original_replace(source, destination)

    monkeypatch.setattr(atomic_module.os, "replace", synchronized_replace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(atomic_replace, path, payload)
            for payload in (b"writer-a", b"writer-b")
        ]
        for future in futures:
            future.result()

    assert len(set(observed_sources)) == 2
    assert path.read_bytes() in {b"writer-a", b"writer-b"}
    assert list(tmp_path.glob("*.tmp")) == []


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
