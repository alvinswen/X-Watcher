"""文件版 ProfileStore:data/profiles/profiles.json 单集合文档。

盘面: {"profiles": {<platform_user_id>: {…21字段…}}}
- 键=platform_user_id(API 不可变主键),无 seq(无 id 分配)
- shard_lock 下 load→mutate→atomic_write_doc
- upsert merge 语义;raw_data_map 接受但不持久化(契约下不可观测,YAGNI)
- 两无序查询顺序不同(实测 sqlite):
  get_profiles_by_user_ids 走 PK 索引→platform_user_id 升序;
  get_profiles_by_usernames lower() 全表扫→插入序
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.preference.domain.models import XUserProfile
from src.preference.infrastructure.profile_store import RepositoryError
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


def _now_naive_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


class FileProfileStore:
    """ProfileStore 的文件实现(6 方法全实现 + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "profiles" / "profiles.json"

    def _load(self) -> dict[str, Any]:
        doc = read_doc(self._path)
        if doc is None:
            return {"profiles": {}}
        return doc

    @staticmethod
    def _to_domain(rec: dict[str, Any]) -> XUserProfile:
        return XUserProfile(**rec)

    # —— 测试种子(非契约方法):按列表顺序写入,控制插入序 ——
    async def seed(self, profiles: list[XUserProfile]) -> None:
        async with shard_lock(self._path):
            recs = {p.platform_user_id: p.model_dump(mode="json") for p in profiles}
            atomic_write_doc(self._path, {"profiles": recs})

    async def upsert_profiles(self, profiles: list[XUserProfile],
                              raw_data_map: dict[str, dict[str, Any]] | None = None) -> int:
        # raw_data_map 接受但不持久化(契约下不可观测,见 spec §1 OUT)
        async with shard_lock(self._path):
            doc = self._load()
            profs = doc["profiles"]
            count = 0
            for p in profiles:
                if not p.platform_user_id:
                    continue                                # 跳过空主键(镜像旧 repo continue)
                rec = p.model_dump(mode="json")
                if rec.get("fetched_at") is None:
                    rec["fetched_at"] = _now_naive_iso()    # fetched_at or now
                profs[p.platform_user_id] = rec             # merge:存在覆盖/不存在插入
                count += 1
            atomic_write_doc(self._path, doc)
            return count

    async def get_profile_by_user_id(self, platform_user_id: str) -> XUserProfile | None:
        # 读路径不加 shard_lock:_load() 同步、其间无 await,asyncio 单事件循环下不会被写
        # 协程交错;os.replace 原子写保证读者要么旧整片要么新整片。若 _load 改异步需补锁。
        rec = self._load()["profiles"].get(platform_user_id)
        return self._to_domain(rec) if rec is not None else None

    async def get_profiles_by_user_ids(self, user_ids: list[str]) -> list[XUserProfile]:
        if not user_ids:
            return []
        wanted = set(user_ids)
        hits = [r for r in self._load()["profiles"].values() if r["platform_user_id"] in wanted]
        hits.sort(key=lambda r: r["platform_user_id"])      # PK autoindex 序(实测,见前置证据)
        return [self._to_domain(r) for r in hits]

    async def get_all_profiles(self) -> list[XUserProfile]:
        items = [self._to_domain(r) for r in self._load()["profiles"].values()]
        items.sort(key=lambda p: p.fetched_at, reverse=True)  # type: ignore[arg-type,return-value]  # fetched_at DESC
        return items

    async def get_profiles_by_usernames(self, usernames: list[str]) -> list[XUserProfile]:
        if not usernames:
            return []
        wanted = {u.lower() for u in usernames}
        # 全表扫插入序(实测):保持 dict 插入序,不排序
        return [self._to_domain(r) for r in self._load()["profiles"].values()
                if (r["username"] or "").lower() in wanted]

    async def get_profile_by_username(self, username: str) -> XUserProfile | None:
        matches = [r for r in self._load()["profiles"].values() if r["username"] == username]
        if not matches:
            return None
        if len(matches) > 1:
            # 镜像旧 repo scalar_one_or_none 多行 → MultipleResultsFound → 包成 RepositoryError
            raise RepositoryError(f"按用户名查询档案失败: 多条记录匹配 username={username}")
        return self._to_domain(matches[0])
