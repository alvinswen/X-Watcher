"""文件版 FollowStore:data/follows/follows.json 单集合文档。

盘面: {"seq": <int>, "follows": {<精确username>: {…11字段…}}}
- seq 承载 id 分配(load 时取 max(现有 id);新建 id=seq+1 单调不复用;reactivate 复用原 id)
- shard_lock 下 load→mutate→atomic_write_doc
- 手动唯一性(无 DB 约束): username 由 dict 键天然唯一; platform_user_id 查重由
  update_platform_user_id 负责
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any

from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.follow_store import (
    DuplicateError,
    NotFoundError,
    RepositoryError,
)
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc

logger = logging.getLogger(__name__)


def _now_naive() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


class FileFollowStore:
    """FollowStore 的文件实现(12 方法全实现 + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "follows" / "follows.json"

    def _load(self) -> dict[str, Any]:
        doc = read_doc(self._path)
        if doc is None:
            return {"seq": 0, "follows": {}}
        return doc

    @staticmethod
    def _to_domain(rec: dict[str, Any]) -> ScraperFollow:
        return ScraperFollow(**rec)

    # —— 测试种子(非契约方法):写入显式字段行,控制 id/added_at/状态 ——
    async def seed(self, follows: list[ScraperFollow]) -> None:
        async with shard_lock(self._path):
            recs = {f.username: f.model_dump(mode="json") for f in follows}
            seq = max((f.id for f in follows), default=0)
            atomic_write_doc(self._path, {"seq": seq, "follows": recs})

    # —— 核心 CRUD ——
    async def create_scraper_follow(self, username: str, reason: str, added_by: str) -> ScraperFollow:
        async with shard_lock(self._path):
            doc = self._load()
            follows = doc["follows"]
            existing = follows.get(username)
            if existing is not None:
                if not existing["is_active"]:
                    existing["is_active"] = True
                    existing["reason"] = reason
                    existing["added_by"] = added_by
                    existing["added_at"] = _now_naive()
                    atomic_write_doc(self._path, doc)
                    return self._to_domain(existing)
                raise DuplicateError(f"抓取账号已存在: {username}")
            doc["seq"] = int(doc["seq"]) + 1
            rec = {
                "id": doc["seq"], "username": username, "added_at": _now_naive(),
                "reason": reason, "added_by": added_by, "is_active": True,
                "manual_limit": None, "platform_user_id": None, "brief_intro": None,
                "backfill_status": "pending", "backfill_completed_at": None,
            }
            follows[username] = rec
            atomic_write_doc(self._path, doc)
            return self._to_domain(rec)

    async def get_all_follows(self, include_inactive: bool = False) -> list[ScraperFollow]:
        # 读路径不加 shard_lock:_load() 为同步、其间无 await,asyncio 单事件循环下不会被写
        # 协程交错;os.replace 原子写保证读者要么旧整片要么新整片。若 _load 改异步需补锁。
        doc = self._load()
        items = [self._to_domain(r) for r in doc["follows"].values()]
        items.sort(key=lambda f: f.added_at, reverse=True)   # added_at DESC
        if not include_inactive:
            items = [f for f in items if f.is_active]
        return items

    async def get_active_follows(self) -> list[ScraperFollow]:
        return await self.get_all_follows(include_inactive=False)

    async def get_follow_by_username(self, username: str) -> ScraperFollow | None:
        rec = self._load()["follows"].get(username)   # 精确大小写
        return self._to_domain(rec) if rec is not None else None

    async def update_scraper_follow(self, username: str, reason: str | None = None,
                                    is_active: bool | None = None, manual_limit: int | None = None,
                                    brief_intro: str | None = None) -> ScraperFollow:
        if reason is None and is_active is None and manual_limit is None and brief_intro is None:
            raise RepositoryError("必须提供至少一个更新参数(reason、is_active、manual_limit 或 brief_intro)")
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["follows"].get(username)
            if rec is None:
                raise NotFoundError(f"抓取账号不存在: {username}")
            if reason is not None:
                rec["reason"] = reason
            if is_active is not None:
                rec["is_active"] = is_active
            if manual_limit is not None:
                rec["manual_limit"] = None if manual_limit == 0 else manual_limit
            if brief_intro is not None:
                rec["brief_intro"] = brief_intro or None
            atomic_write_doc(self._path, doc)
            return self._to_domain(rec)

    async def deactivate_follow(self, username: str) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["follows"].get(username)
            if rec is None:
                raise NotFoundError(f"抓取账号不存在: {username}")
            rec["is_active"] = False
            atomic_write_doc(self._path, doc)

    async def update_platform_user_id(self, username: str, platform_user_id: str) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["follows"].get(username)
            if rec is None or rec["platform_user_id"]:
                return                                  # 不存在或已有值 → 不写(幂等回填)
            # 手动唯一性:platform_user_id 已被占用 → warn 不抛(镜像旧 IntegrityError 分支)
            if any(r["platform_user_id"] == platform_user_id for r in doc["follows"].values()):
                logger.warning("platform_user_id 已被其他账号占用: %s", platform_user_id)
                return
            rec["platform_user_id"] = platform_user_id
            atomic_write_doc(self._path, doc)

    async def update_username(self, old_username: str, new_username: str) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            follows = doc["follows"]
            rec = follows.get(old_username)
            if rec is None:
                raise NotFoundError(f"抓取账号不存在: {old_username}")
            if new_username in follows:
                raise DuplicateError(f"新用户名已被占用: {new_username}")
            rec["username"] = new_username
            follows[new_username] = follows.pop(old_username)
            atomic_write_doc(self._path, doc)

    async def get_follow_by_platform_user_id(self, platform_user_id: str) -> ScraperFollow | None:
        for rec in self._load()["follows"].values():
            if rec["platform_user_id"] == platform_user_id:
                return self._to_domain(rec)
        return None

    async def get_pending_backfill_users(self) -> list[ScraperFollow]:
        items = [self._to_domain(r) for r in self._load()["follows"].values()
                 if r["is_active"] and r["backfill_status"] == "pending"]
        items.sort(key=lambda f: f.added_at)            # added_at ASC
        return items

    async def update_backfill_status(self, username: str, status: str,
                                     completed_at: datetime | None = None) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["follows"].get(username)
            if rec is None:
                raise NotFoundError(f"抓取账号不存在: {username}")
            rec["backfill_status"] = status
            if completed_at is not None:
                rec["backfill_completed_at"] = completed_at.isoformat()
            atomic_write_doc(self._path, doc)

    async def upsert_follow(self, fields: dict[str, Any]) -> None:
        """按 username 插入或全字段覆盖(import 写底座;fields=导出格式 10 字段,无 id)。
        存在→保留原 id 覆盖其余;不存在→分配 seq+1。datetime 串保持导出格式,read-back 归一化。"""
        async with shard_lock(self._path):
            doc = self._load()
            follows = doc["follows"]
            username = fields["username"]
            existing = follows.get(username)
            if existing is not None:
                rec = {**fields, "id": existing["id"]}
            else:
                doc["seq"] = int(doc["seq"]) + 1
                rec = {**fields, "id": doc["seq"]}
            follows[username] = rec
            atomic_write_doc(self._path, doc)
