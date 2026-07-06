# src/scraper/infrastructure/file_fetch_stats_repository.py
"""文件版 FetchStatsStore:data/fetch_stats/fetch_stats.json 单集合文档。

盘面: {"fetch_stats": {<username>: {…7字段…}}}
- 键=username(调用方提供的不可变主键,无 id 分配);无外部 FK
- shard_lock 下 load→mutate→atomic_write_doc(写路径);读路径无锁(同前八片)
- upsert_stats insert-or-update:整条 model_dump 覆盖(≡ oracle 改 6 业务字段,因域模型仅 7 字段、
  username 不变;与 article save 跳过反向——这里命中即覆盖,不做 exists 检查)
- batch_get_stats:IN→dict,只含存在的(缺失 username 不占位);空列表→{};不排序(parity dict 无序比较)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.scraper.domain.fetch_stats import FetchStats
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


class FileFetchStatsStore:
    """FetchStatsStore 的文件实现(3 方法 + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "fetch_stats" / "fetch_stats.json"

    def _load(self) -> dict[str, Any]:
        doc = read_doc(self._path)
        if doc is None:
            return {"fetch_stats": {}}
        return doc

    @staticmethod
    def _to_domain(rec: dict[str, Any]) -> FetchStats:
        return FetchStats(**rec)

    # —— 测试种子(非契约方法):按列表批量写入(fetch_stats 按 username key 访问,无顺序依赖) ——
    async def seed(self, stats_list: list[FetchStats]) -> None:
        async with shard_lock(self._path):
            recs = {s.username: s.model_dump(mode="json") for s in stats_list}
            atomic_write_doc(self._path, {"fetch_stats": recs})

    async def get_stats(self, username: str) -> FetchStats | None:
        rec = self._load()["fetch_stats"].get(username)
        return self._to_domain(rec) if rec is not None else None

    async def batch_get_stats(self, usernames: list[str]) -> dict[str, FetchStats]:
        if not usernames:
            return {}
        recs = self._load()["fetch_stats"]
        return {u: self._to_domain(recs[u]) for u in usernames if u in recs}

    async def upsert_stats(self, stats: FetchStats) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            doc["fetch_stats"][stats.username] = stats.model_dump(mode="json")
            atomic_write_doc(self._path, doc)
