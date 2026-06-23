"""文件版 ScheduleStore:data/schedule/schedule.json 单文档直存 config。

盘面: {id, interval_seconds, next_run_time, is_enabled, updated_at, updated_by}
- 单例退化形态:文件直接是一条 config(无包裹层),文件不存在=无配置=get 返 None
- shard_lock 下 read_doc→mutate→atomic_write_doc
- upsert 语义逐条镜像旧 ScraperScheduleRepository@77e41a4:
  create 逐字段兜底(吃传入参)、update 仅 if not None 才改(next_run 传 None 不清除)、
  updated_by 无条件覆盖(默认 "")、updated_at=now 恒派生
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.preference.domain.models import ScraperScheduleConfig
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FileScheduleStore:
    """ScheduleStore 的文件实现(2 方法 + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "schedule" / "schedule.json"

    @staticmethod
    def _to_domain(rec: dict) -> ScraperScheduleConfig:
        return ScraperScheduleConfig(**rec)

    # —— 测试种子(非契约方法):直接写一条 config,不经被测 upsert ——
    async def seed(self, config: ScraperScheduleConfig) -> None:
        async with shard_lock(self._path):
            atomic_write_doc(self._path, config.model_dump(mode="json"))

    async def get_schedule_config(self) -> ScraperScheduleConfig | None:
        # 读路径不加 shard_lock:read_doc/_to_domain 同步、其间无 await,asyncio 单事件循环下不会被写
        doc = read_doc(self._path)
        if doc is None:
            return None                                  # 文件不存在=无配置
        return self._to_domain(doc)

    async def upsert_schedule_config(
        self,
        interval_seconds: int | None = None,
        next_run_time: datetime | None = None,
        is_enabled: bool | None = None,
        updated_by: str = "",
    ) -> ScraperScheduleConfig:
        async with shard_lock(self._path):
            doc = read_doc(self._path)
            now = _now_naive()
            if doc is None:
                # create 分支:逐字段兜底(精化①,吃传入参)
                config = ScraperScheduleConfig(
                    id=1,
                    interval_seconds=interval_seconds if interval_seconds is not None else 43200,
                    next_run_time=next_run_time,
                    is_enabled=is_enabled if is_enabled is not None else True,
                    updated_at=now,
                    updated_by=updated_by,
                )
            else:
                # update 分支:interval/next_run/is_enabled 仅 if not None 才改(next_run 传 None 不清除);
                # updated_by 无条件覆盖(精化②);updated_at=now
                existing = self._to_domain(doc)
                config = ScraperScheduleConfig(
                    id=existing.id,
                    interval_seconds=interval_seconds if interval_seconds is not None else existing.interval_seconds,
                    next_run_time=next_run_time if next_run_time is not None else existing.next_run_time,
                    is_enabled=is_enabled if is_enabled is not None else existing.is_enabled,
                    updated_at=now,
                    updated_by=updated_by,
                )
            atomic_write_doc(self._path, config.model_dump(mode="json"))
            return config

    async def overwrite_schedule_config(self, fields: dict) -> None:
        """插入或全字段覆盖 singleton(import 写底座;fields=导出格式 5 字段;id 恒 1;
        updated_at 取 fields 值【非 now】,镜像 import overwrite 用 dict 时间戳)。"""
        async with shard_lock(self._path):
            atomic_write_doc(self._path, {"id": 1, **fields})
