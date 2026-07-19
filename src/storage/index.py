"""内存 tweet_id 索引(启动构建 + 增量更新);持久化索引为未来逃生舱。"""

from __future__ import annotations

from pathlib import Path

from src.storage.jsonl_store import read_shard
from src.storage.paths import iter_canonical_shards


class TweetIdIndex:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    @classmethod
    def build(cls, data_root: Path) -> TweetIdIndex:
        idx = cls()
        for shard in iter_canonical_shards(data_root):
            for rec in read_shard(shard):
                tid = rec.get("tweet_id")
                if tid:
                    idx._ids.add(tid)
        return idx

    def contains(self, tweet_id: str) -> bool:
        return tweet_id in self._ids

    def filter_existing(self, tweet_ids: list[str]) -> set[str]:
        return {t for t in tweet_ids if t in self._ids}

    def add(self, tweet_id: str) -> None:
        self._ids.add(tweet_id)
