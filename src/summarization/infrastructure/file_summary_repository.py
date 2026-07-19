# src/summarization/infrastructure/file_summary_repository.py
"""文件版 SummaryStore:data/summaries/summaries.json 单集合文档。

盘面: {"summaries": {<summary_id>: {…15字段…}}}
- 键=summary_id(调用方提供的 UUID,无 id 分配);tweet_id 是对 tweets 的纯字符串 JSON 引用(无 FK)
- shard_lock 下 load→mutate→atomic_write_doc(写路径);读路径无锁(同前三片)
- save 复合键 (tweet_id,content_hash) 去重 latest-wins(命中改 11 传入字段 + updated_at=now、保留 existing
  summary_id/created_at;返回值=传入 record copy 仅换 summary_id)
- get_by_tweet 多行抛(scalar_one_or_none)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.summary_store import RepositoryError


def _now_naive_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


class FileSummaryStore:
    """摘要文件存储(save_summary_record/get_summary_by_tweet + sync 底座 get_all/exists/upsert + seed 测试种子)。"""

    _MUT_FIELDS = ("summary_text", "translation_text", "model_provider", "model_name",
                   "prompt_tokens", "completion_tokens", "total_tokens", "cost_usd",
                   "cached", "is_generated_summary", "content_hash")

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "summaries" / "summaries.json"

    def _load(self) -> dict[str, Any]:
        doc = read_doc(self._path)
        if doc is None:
            return {"summaries": {}}
        return doc

    @staticmethod
    def _to_domain(rec: dict[str, Any]) -> SummaryRecord:
        return SummaryRecord(**rec)

    # —— 测试种子(非契约方法):按列表顺序写入,控制插入序 ——
    async def seed(self, records: list[SummaryRecord]) -> None:
        async with shard_lock(self._path):
            recs = {r.summary_id: r.model_dump(mode="json") for r in records}
            atomic_write_doc(self._path, {"summaries": recs})

    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord:
        try:
            async with shard_lock(self._path):
                doc = self._load()
                summaries = doc["summaries"]
                # 按 (tweet_id, content_hash) 找已有、created_at desc 取最新一条(≡ order_by desc limit 1)
                matches = [r for r in summaries.values()
                           if r["tweet_id"] == record.tweet_id and r["content_hash"] == record.content_hash]
                existing = max(matches, key=lambda r: r["created_at"]) if matches else None
                if existing is not None:
                    # 更新已有记录的 11 传入字段 + 下方 updated_at=now(保留 existing 的 summary_id/tweet_id/created_at)
                    rec = record.model_dump(mode="json")
                    for f in self._MUT_FIELDS:
                        existing[f] = rec[f]
                    existing["updated_at"] = _now_naive_iso()
                    atomic_write_doc(self._path, doc)
                    # 返回值:传入 record copy 仅换 summary_id(created_at/updated_at 保持传入值)
                    return record.model_copy(update={"summary_id": existing["summary_id"]})
                # 创建新记录
                summaries[record.summary_id] = record.model_dump(mode="json")
                atomic_write_doc(self._path, doc)
                return record
        except Exception as e:  # noqa: BLE001
            raise RepositoryError(f"保存摘要记录失败: {e}") from e

    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None:
        matches = [r for r in self._load()["summaries"].values() if r["tweet_id"] == tweet_id]
        if len(matches) > 1:
            # 镜像 scalar_one_or_none 多行 → MultipleResultsFound → 包成 RepositoryError
            raise RepositoryError(f"查询推文摘要失败: 多条记录匹配 tweet_id={tweet_id}")
        if not matches:
            return None
        return self._to_domain(matches[0])

    async def get_all_summaries(self) -> list[SummaryRecord]:
        """枚举全部摘要记录(无序;Export 全量读)。"""
        return [self._to_domain(r) for r in self._load()["summaries"].values()]

    async def summary_exists(self, summary_id: str) -> bool:
        return summary_id in self._load()["summaries"]

    async def upsert_summary(self, fields: dict[str, Any]) -> None:
        """按 summary_id 插入或全字段覆盖(import 写底座;fields=导出格式 14 字段)。
        updated_at 不在导出面→取 created_at(确定性,read-back 不投影)。"""
        async with shard_lock(self._path):
            doc = self._load()
            doc["summaries"][fields["summary_id"]] = {**fields, "updated_at": fields["created_at"]}
            atomic_write_doc(self._path, doc)
