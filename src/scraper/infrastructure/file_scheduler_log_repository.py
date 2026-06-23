# src/scraper/infrastructure/file_scheduler_log_repository.py
"""文件版 SchedulerLogStore:data/scheduler_logs/scheduler_logs.json 单集合 append-only 日志。

盘面: {"seq": <int>, "logs": [ {…8 域字段…}, … ]}
- logs append-only 列表(无自然键);seq 承载 id 分配(持久、单调 +1、cleanup 硬删除后不回收,比 sqlite
  rowid 删最大行后可能回收更强)
- 不存 created_at(域模型无、不可观测)
- shard_lock 下 load→mutate→atomic_write_doc(写路径:seed/cleanup/write_log);读路径(get_recent_logs)无锁
- get_recent_logs:load→to_domain→executed_at desc(stable sort,相同时点 tie-break 由 fixtures 互异规避)→
  可选 event_type/since 过滤→limit
- cleanup_old_logs:cutoff=now(utc)-retention;保留 executed_at>=cutoff;返回删除数;seq 不变(不回收 id)
- write_log(async,carve-out):seq+1 分配 id、append、原子写;异常仅 log 不抛(镜像旧 SyncWriter)
- ⚠️ sync writer carve-out:旧 SchedulerExecutionLogSyncWriter.write_log 静态同步走全局引擎,本片数据层统一
  async;应用层 sync/APScheduler 桥接属 M-5 接活
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    """naive 视为 UTC(供 cleanup/since 比较规整,绝不让 naive/aware 比较抛 TypeError)。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class FileSchedulerLogStore:
    """SchedulerLogStore 的文件实现(get_recent_logs/cleanup_old_logs/write_log + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "scheduler_logs" / "scheduler_logs.json"

    def _load(self) -> dict:
        doc = read_doc(self._path)
        if doc is None:
            return {"seq": 0, "logs": []}
        return doc

    @staticmethod
    def _to_domain(rec: dict) -> SchedulerExecutionLog:
        return SchedulerExecutionLog(**rec)

    # —— 测试种子(非契约方法):按列表序写入,逐条分配 id=seq+1 ——
    async def seed(self, logs: list[SchedulerExecutionLog]) -> None:
        async with shard_lock(self._path):
            recs = []
            seq = 0
            for log in logs:
                seq += 1
                rec = log.model_dump(mode="json")
                rec["id"] = seq
                recs.append(rec)
            atomic_write_doc(self._path, {"seq": seq, "logs": recs})

    async def get_recent_logs(
        self,
        limit: int = 50,
        event_type: SchedulerEventType | None = None,
        since: datetime | None = None,
    ) -> list[SchedulerExecutionLog]:
        # 读路径不加锁:_load 同步、其间无 await(同前八片注释)
        logs = [self._to_domain(r) for r in self._load()["logs"]]
        logs.sort(key=lambda l: l.executed_at, reverse=True)   # executed_at DESC
        if event_type is not None:
            logs = [l for l in logs if l.event_type == event_type]
        if since is not None:
            logs = [l for l in logs if _as_utc(l.executed_at) >= _as_utc(since)]
        return logs[:limit]

    async def cleanup_old_logs(self, retention_days: int = 30) -> int:
        async with shard_lock(self._path):
            doc = self._load()
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            kept = [r for r in doc["logs"]
                    if _as_utc(datetime.fromisoformat(r["executed_at"])) >= cutoff]
            deleted = len(doc["logs"]) - len(kept)
            atomic_write_doc(self._path, {"seq": doc["seq"], "logs": kept})   # seq 不变 → 不回收
            return deleted

    async def write_log(self, log: SchedulerExecutionLog) -> None:
        # carve-out:async append;异常仅 log 不抛(镜像旧 SchedulerExecutionLogSyncWriter.write_log)
        try:
            async with shard_lock(self._path):
                doc = self._load()
                doc["seq"] = int(doc["seq"]) + 1
                rec = log.model_dump(mode="json")
                rec["id"] = doc["seq"]
                doc["logs"].append(rec)
                atomic_write_doc(self._path, doc)
        except Exception as e:  # noqa: BLE001
            logger.error("写入调度器执行日志失败: %s", e, exc_info=True)
