#!/usr/bin/env python3
"""Migrate the legacy summary document into monthly JSONL shards."""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import src.shared.read_cache as read_cache_module
import src.summarization.infrastructure.file_summary_repository as summary_repository_module
from src.shared.read_cache import load_summary_map
from src.storage.doc_store import read_doc
from src.storage.jsonl_store import read_shard, write_shard
from src.storage.paths import iter_summary_shards, summary_legacy_doc, summary_shard
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate summaries.json into summaries/<YYYY-MM>.jsonl shards.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Data root; defaults to XWATCHER_DATA_ROOT.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and group records without writing (default).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Write shards, verify them through A-D, then archive the legacy file.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing monthly shards; only takes effect with --execute.",
    )
    return parser.parse_args()


def _data_root(args: argparse.Namespace) -> Path:
    value = args.data_root or os.environ.get("XWATCHER_DATA_ROOT")
    if value is None:
        raise RuntimeError("请通过 --data-root 或 XWATCHER_DATA_ROOT 指定数据根目录")
    return Path(value).expanduser().resolve()


def _load_before(root: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    legacy = summary_legacy_doc(root)
    document = read_doc(legacy)
    if document is None:
        raise RuntimeError(f"旧摘要文件不存在: {legacy}")
    raw = document.get("summaries")
    if not isinstance(raw, dict):
        raise RuntimeError(f"旧摘要文件缺少 summaries 字典: {legacy}")

    before: dict[str, dict[str, Any]] = {}
    for summary_id, record in raw.items():
        if not isinstance(record, dict):
            raise RuntimeError(f"摘要记录不是对象: summary_id={summary_id}")
        before[str(summary_id)] = record
    return legacy, before


def _group_records(
    root: Path,
    before: dict[str, dict[str, Any]],
) -> dict[Path, list[dict[str, Any]]]:
    grouped: dict[Path, list[dict[str, Any]]] = {}
    total = len(before)
    for number, record in enumerate(before.values(), start=1):
        created_at = datetime.fromisoformat(str(record["created_at"]))
        target = summary_shard(root, created_at)
        grouped.setdefault(target, []).append(record)
        if number % 5_000 == 0 or number == total:
            print(f"已处理 {number} / 总数 {total}")
    if total == 0:
        print("已处理 0 / 总数 0")
    return grouped


def _verify_structure(root: Path, before: dict[str, dict[str, Any]]) -> None:
    after: dict[str, dict[str, Any]] = {}
    for path in iter_summary_shards(root):
        for record in read_shard(path):
            summary_id = str(record["summary_id"])
            if summary_id in after:
                raise RuntimeError(f"重复 summary_id 跨分片: {summary_id}")
            expected = summary_shard(
                root,
                datetime.fromisoformat(str(record["created_at"])),
            )
            if expected != path:
                raise RuntimeError(f"记录落错分片: summary_id={summary_id} actual={path}")
            after[summary_id] = record

    if len(after) != len(before):
        raise RuntimeError(f"条数不一致 {len(after)} != {len(before)}")
    if after != before:
        raise RuntimeError("逐条内容不一致")
    print(f"A-C 核对通过: records={len(after)} shards={len(iter_summary_shards(root))}")


async def _verify_runtime(root: Path, before: dict[str, dict[str, Any]]) -> None:
    cache_key = str(root)
    summary_repository_module._locator_cache.pop(cache_key, None)
    read_cache_module._summary_cache.pop(cache_key, None)

    store = FileSummaryStore(root)
    runtime_records = await store.get_all_summaries()
    if len(runtime_records) != len(before):
        raise RuntimeError(
            "运行时读路径条数不符: "
            f"get_all_summaries={len(runtime_records)} != 迁移前={len(before)}"
        )
    if {record.summary_id for record in runtime_records} != set(before):
        raise RuntimeError("运行时读路径的 summary_id 集合与迁移前不一致")

    runtime_map = await load_summary_map(root)
    expected_tweet_ids = {str(record["tweet_id"]) for record in before.values()}
    if len(runtime_map) != len(expected_tweet_ids):
        raise RuntimeError(
            "读缓存路径 tweet_id 数不符: "
            f"load_summary_map={len(runtime_map)} != 迁移前去重={len(expected_tweet_ids)}"
        )
    if set(runtime_map) != expected_tweet_ids:
        raise RuntimeError("读缓存路径的 tweet_id 集合与迁移前不一致")

    for tweet_id in random.sample(
        sorted(expected_tweet_ids),
        k=min(3, len(expected_tweet_ids)),
    ):
        found = await store.get_summary_by_tweet(tweet_id)
        if found is None:
            raise RuntimeError(f"运行时按 tweet_id 查不到: {tweet_id}")
    print(
        "D 核对通过: "
        f"runtime_records={len(runtime_records)} unique_tweet_ids={len(runtime_map)}"
    )


def _archive_legacy(legacy: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = legacy.with_name(f"{legacy.name}.migrated-{timestamp}")
    if archive.exists():
        raise RuntimeError(f"归档目标已存在: {archive}")
    legacy.rename(archive)
    return archive


def main() -> int:
    args = _parse_args()
    try:
        root = _data_root(args)
        legacy, before = _load_before(root)
        existing = iter_summary_shards(root)
        if existing and not args.force:
            names = ", ".join(path.name for path in existing[:5])
            raise RuntimeError(f"已存在月分片，拒绝重复迁移（可用 --force）: {names}")

        mode = "EXECUTE" if args.execute else "DRY-RUN"
        print(f"{mode}: data_root={root} legacy={legacy} records={len(before)}")
        grouped = _group_records(root, before)
        for path in sorted(grouped):
            print(f"- {path.name}: {len(grouped[path])}")

        if not args.execute:
            print("DRY-RUN only; 未写分片、未改名原文件。使用 --execute 执行迁移。")
            return 0

        if args.force:
            for path in existing:
                path.unlink(missing_ok=True)
            if existing:
                print(f"--force 已移除既有月分片: {len(existing)}")

        for path in sorted(grouped):
            write_shard(path, grouped[path])
        print(f"写入完成: shards={len(grouped)} records={len(before)}")

        _verify_structure(root, before)
        asyncio.run(_verify_runtime(root, before))
        archive = _archive_legacy(legacy)
        print(f"迁移成功: legacy_archive={archive}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "原文件未被脚本改写；若已产生半成品月分片，请保持停手窗口并删除后重试。",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
