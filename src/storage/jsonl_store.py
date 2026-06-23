"""JSONL 分片读写引擎(高频流式实体)。"""

from __future__ import annotations

import json
from pathlib import Path

from src.storage.atomic import atomic_replace


def read_shard(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # 坏行跳过(可由 rebuild 修),不让整片读崩
            continue
    return records


def write_shard(path: Path, records: list[dict]) -> None:
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    if payload:
        payload += "\n"
    atomic_replace(Path(path), payload.encode("utf-8"))


def upsert(path: Path, new_records: list[dict], key: str = "tweet_id") -> int:
    existing = read_shard(path)
    by_key = {r[key]: r for r in existing}
    added = 0
    for rec in new_records:
        if rec[key] not in by_key:
            added += 1
        by_key[rec[key]] = rec
    write_shard(path, list(by_key.values()))
    return added
