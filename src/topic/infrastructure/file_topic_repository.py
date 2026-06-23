"""文件版 TopicStore:data/topics/topics.json 单文件双集合。

盘面: {"topics": {<id>: {…6字段…}}, "accounts": {<id>: {…4字段…}}, "_seq": {"topics": N, "accounts": M}}
- _seq.topics / _seq.accounts 各自 autoincrement +1 单调不回收(delete 不回收 seq;同 follows)
- shard_lock 下 load→mutate→atomic_write_doc(写路径);读路径无锁(同前四片)
- 手动唯一性:create 检 (user_id,name)、add_account 检 (topic_id,username),冲突 DuplicateError
  (含 user_id=NULL 也强制,比 sqlite NULL-允许重复 更严 → changed,出 parity 入 invariant)
- get_by_id 关系加载:扫 accounts 拼 TopicDetail(id 升序);get_by_name 不加载 accounts
- delete 契约面内级联删 accounts(A 片范围;tasks/summaries 由 B 片回补);单次原子写
- list_all 关联聚合 account_count(全扫计数)+ created_at DESC + user_id 过滤(None=全部)
- get_by_name 的 user_id=None → 只匹配 user_id is None(复刻 SQL IS NULL,与 list_all None 相反)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.topic.domain.models import (
    TopicAccountDomain,
    TopicDetailDomain,
    TopicDomain,
    TopicWithCountDomain,
)
from src.topic.infrastructure.topic_store import DuplicateError, NotFoundError
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


def _now_naive() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class FileTopicStore:
    """TopicStore 的文件实现(11 方法全实现 + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "topics" / "topics.json"

    def _load(self) -> dict:
        doc = read_doc(self._path)
        if doc is None:
            doc = {}
        doc.setdefault("topics", {})
        doc.setdefault("accounts", {})
        doc.setdefault("tasks", {})          # B 片回补:四集合归一化(向后兼容 A 片双集合 doc)
        doc.setdefault("summaries", {})
        seq = doc.setdefault("_seq", {})
        for _k in ("topics", "accounts", "tasks", "summaries"):
            seq.setdefault(_k, 0)
        return doc

    @staticmethod
    def _to_topic(rec: dict) -> TopicDomain:
        return TopicDomain(**rec)

    @staticmethod
    def _to_account(rec: dict) -> TopicAccountDomain:
        return TopicAccountDomain(**rec)

    @staticmethod
    def _accounts_of(doc: dict, topic_id: int) -> list[dict]:
        return sorted(
            (a for a in doc["accounts"].values() if a["topic_id"] == topic_id),
            key=lambda a: a["id"],
        )

    # —— 测试种子(非契约方法):写入显式字段行,控制 id/时间 ——
    async def seed(
        self,
        topics: list[TopicDomain],
        accounts: list[TopicAccountDomain] | None = None,
    ) -> None:
        async with shard_lock(self._path):
            t_recs = {str(t.id): t.model_dump(mode="json") for t in topics}
            a_recs = {str(a.id): a.model_dump(mode="json") for a in (accounts or [])}
            seq = {
                "topics": max((t.id for t in topics), default=0),
                "accounts": max((a.id for a in (accounts or [])), default=0),
            }
            atomic_write_doc(self._path, {"topics": t_recs, "accounts": a_recs, "_seq": seq})

    # —— 话题 ——
    async def create(
        self, name: str, description: str | None = None, user_id: int | None = None
    ) -> TopicDomain:
        async with shard_lock(self._path):
            doc = self._load()
            for t in doc["topics"].values():           # 手动唯一性(含 NULL)
                if t["user_id"] == user_id and t["name"] == name:
                    raise DuplicateError(f"主题已存在: name={name}, user_id={user_id}")
            doc["_seq"]["topics"] = int(doc["_seq"]["topics"]) + 1
            tid = doc["_seq"]["topics"]
            now = _now_naive()
            rec = {
                "id": tid, "name": name, "description": description, "user_id": user_id,
                "created_at": now, "updated_at": now,
            }
            doc["topics"][str(tid)] = rec
            atomic_write_doc(self._path, doc)
            return self._to_topic(rec)

    async def get_by_id(self, topic_id: int) -> TopicDetailDomain | None:
        # 读路径不加 shard_lock:_load() 为同步、其间无 await,asyncio 单事件循环下不会被写
        # 协程交错;os.replace 原子写保证读者要么旧整片要么新整片。若 _load 改异步需补锁。
        doc = self._load()
        rec = doc["topics"].get(str(topic_id))
        if rec is None:
            return None
        accounts = [self._to_account(a) for a in self._accounts_of(doc, topic_id)]
        return TopicDetailDomain(**rec, accounts=accounts)

    async def get_by_name(self, name: str, user_id: int | None = None) -> TopicDomain | None:
        for t in self._load()["topics"].values():
            # user_id=None → 匹配 user_id is None(复刻 SQL IS NULL,与 list_all None 相反)
            if t["name"] == name and t["user_id"] == user_id:
                return self._to_topic(t)
        return None

    async def list_all(self, user_id: int | None = None) -> list[TopicWithCountDomain]:
        doc = self._load()
        topics = list(doc["topics"].values())
        if user_id is not None:                    # None → 不过滤(返回全部)
            topics = [t for t in topics if t["user_id"] == user_id]
        topics.sort(key=lambda t: t["created_at"], reverse=True)   # created_at DESC
        out = []
        for t in topics:
            cnt = sum(1 for a in doc["accounts"].values() if a["topic_id"] == t["id"])
            out.append(TopicWithCountDomain(**t, account_count=cnt))
        return out

    async def update(self, topic: TopicDomain) -> TopicDomain:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["topics"].get(str(topic.id))
            if rec is None:                        # 防御:旧 repo 假设存在,parity 不测此路径
                raise NotFoundError(f"主题不存在: {topic.id}")
            rec["name"] = topic.name
            rec["description"] = topic.description
            rec["user_id"] = topic.user_id
            rec["updated_at"] = _now_naive()       # 镜像 onupdate=now
            atomic_write_doc(self._path, doc)
            return self._to_topic(rec)

    async def delete(self, topic_id: int) -> bool:
        async with shard_lock(self._path):
            doc = self._load()
            if str(topic_id) not in doc["topics"]:
                return False
            del doc["topics"][str(topic_id)]
            # 完整三层级联(B 片回补):删 accounts + tasks + 这些 tasks 的 summaries(单次原子写)
            doc["accounts"] = {k: a for k, a in doc["accounts"].items() if a["topic_id"] != topic_id}
            gone_task_ids = {t["id"] for t in doc["tasks"].values() if t["topic_id"] == topic_id}
            doc["tasks"] = {k: t for k, t in doc["tasks"].items() if t["topic_id"] != topic_id}
            doc["summaries"] = {k: s for k, s in doc["summaries"].items()
                                if s["task_id"] not in gone_task_ids}
            atomic_write_doc(self._path, doc)
            return True

    # —— 账号 ——
    async def add_account(self, topic_id: int, username: str) -> TopicAccountDomain:
        async with shard_lock(self._path):
            doc = self._load()
            for a in doc["accounts"].values():         # 手动唯一性
                if a["topic_id"] == topic_id and a["username"] == username:
                    raise DuplicateError(
                        f"主题账号已存在: topic_id={topic_id}, username={username}"
                    )
            doc["_seq"]["accounts"] = int(doc["_seq"]["accounts"]) + 1
            aid = doc["_seq"]["accounts"]
            rec = {"id": aid, "topic_id": topic_id, "username": username, "added_at": _now_naive()}
            doc["accounts"][str(aid)] = rec
            atomic_write_doc(self._path, doc)
            return self._to_account(rec)

    async def get_account(self, topic_id: int, username: str) -> TopicAccountDomain | None:
        for a in self._load()["accounts"].values():
            if a["topic_id"] == topic_id and a["username"] == username:
                return self._to_account(a)
        return None

    async def get_accounts(self, topic_id: int) -> list[TopicAccountDomain]:
        return [self._to_account(a) for a in self._accounts_of(self._load(), topic_id)]

    async def delete_account(self, topic_id: int, username: str) -> bool:
        async with shard_lock(self._path):
            doc = self._load()
            to_del = [
                k for k, a in doc["accounts"].items()
                if a["topic_id"] == topic_id and a["username"] == username
            ]
            for k in to_del:
                del doc["accounts"][k]
            atomic_write_doc(self._path, doc)
            return len(to_del) > 0                 # rowcount > 0

    async def replace_accounts(
        self, topic_id: int, usernames: list[str]
    ) -> list[TopicAccountDomain]:
        async with shard_lock(self._path):
            doc = self._load()
            doc["accounts"] = {
                k: a for k, a in doc["accounts"].items() if a["topic_id"] != topic_id
            }
            new = []
            for u in usernames:
                doc["_seq"]["accounts"] = int(doc["_seq"]["accounts"]) + 1
                aid = doc["_seq"]["accounts"]
                rec = {"id": aid, "topic_id": topic_id, "username": u, "added_at": _now_naive()}
                doc["accounts"][str(aid)] = rec
                new.append(rec)
            atomic_write_doc(self._path, doc)
            return [self._to_account(r) for r in new]
