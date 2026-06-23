# src/topic/infrastructure/file_topic_summary_task_repository.py
"""文件版 TopicTaskStore:复用 data/topics/topics.json 四集合(topics/accounts/tasks/summaries)。

盘面: {topics:{}, accounts:{}, tasks:{<id>:{11}}, summaries:{<id>:{13}}, _seq:{4 计数}}
- task 存 11 字段(含 tz_offset 存但不出域:to_domain 不投影、域模型无此字段、永不入 parity)
- summary 存 13 字段(含 metadata_json dict);topic_name/summary 不存,读时跨集合 join
- shard_lock 写路径;读路径无锁(同前六片);autoincrement seq +1 不回收
- create_summary 手动唯一性 task_id 一对一(冲突 DuplicateError;changed 出 parity 入 invariant)
- delete_task 契约面内级联删其 summary;delete_topic 完整级联(委派 FileTopicStore.delete)
- get_latest_completed_task: status==completed + completed_at DESC limit 1
  (None 排最后:排序键 (completed_at is not None, completed_at or "") + reverse;镜像 sqlite DESC NULL-last)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.topic.domain.models import (
    TopicSummaryDomain, TopicSummaryTaskDomain, TopicSummaryTaskStatus,
)
from src.topic.infrastructure.file_topic_repository import FileTopicStore
from src.topic.infrastructure.topic_task_store import DuplicateError, NotFoundError
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


def _now_naive() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _iso(x):
    return x.isoformat() if isinstance(x, datetime) else x   # None/str 原样


def _task_to_rec(t: TopicSummaryTaskDomain) -> dict:
    d = t.model_dump(mode="json")
    d.pop("topic_name", None)        # 派生,不存
    d.pop("summary", None)           # 派生,不存
    d["tz_offset"] = 0               # 不在域,seed 默认 0(parity 不涉)
    return d


class FileTopicSummaryTaskStore:
    """TopicTaskStore 的文件实现(8 契约方法 + seed + delete_topic 委派 FileTopicStore)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "topics" / "topics.json"
        self._topic = FileTopicStore(data_root)      # delete_topic 委派(完整级联)

    def _load(self) -> dict:
        doc = read_doc(self._path)
        if doc is None:
            doc = {}
        doc.setdefault("topics", {})
        doc.setdefault("accounts", {})
        doc.setdefault("tasks", {})
        doc.setdefault("summaries", {})
        seq = doc.setdefault("_seq", {})
        for _k in ("topics", "accounts", "tasks", "summaries"):
            seq.setdefault(_k, 0)
        return doc

    @staticmethod
    def _summary_rec_of(doc: dict, task_id: int) -> dict | None:
        for s in doc["summaries"].values():
            if s["task_id"] == task_id:
                return s
        return None

    def _to_task_domain(self, doc: dict, rec: dict) -> TopicSummaryTaskDomain:
        # topic_name 来自父表 topics(FK 保证存在);summary 来自 summaries(task_id 唯一)
        topic_name = doc["topics"][str(rec["topic_id"])]["name"]
        s_rec = self._summary_rec_of(doc, rec["id"])
        summary = TopicSummaryDomain(**s_rec) if s_rec is not None else None
        return TopicSummaryTaskDomain(
            id=rec["id"], topic_id=rec["topic_id"], topic_name=topic_name,
            time_span_hours=rec["time_span_hours"], deadline=rec["deadline"],
            custom_prompt=rec["custom_prompt"], status=TopicSummaryTaskStatus(rec["status"]),
            error_message=rec["error_message"], created_at=rec["created_at"],
            started_at=rec["started_at"], completed_at=rec["completed_at"], summary=summary)

    # —— 测试种子(非契约方法):写四集合,控制 id/时间 ——
    async def seed(self, topics, tasks=None, summaries=None) -> None:
        async with shard_lock(self._path):
            t_recs = {str(t.id): t.model_dump(mode="json") for t in topics}
            task_recs = {str(x.id): _task_to_rec(x) for x in (tasks or [])}
            sum_recs = {str(x.id): x.model_dump(mode="json") for x in (summaries or [])}
            seq = {"topics": max((t.id for t in topics), default=0), "accounts": 0,
                   "tasks": max((x.id for x in (tasks or [])), default=0),
                   "summaries": max((x.id for x in (summaries or [])), default=0)}
            atomic_write_doc(self._path, {"topics": t_recs, "accounts": {},
                                          "tasks": task_recs, "summaries": sum_recs, "_seq": seq})

    # —— 摘要任务 ——
    async def create_task(self, topic_id, time_span_hours, deadline, custom_prompt=None,
                          tz_offset=0, status="pending", error_message=None,
                          started_at=None, completed_at=None) -> TopicSummaryTaskDomain:
        async with shard_lock(self._path):
            doc = self._load()
            doc["_seq"]["tasks"] = int(doc["_seq"]["tasks"]) + 1
            tid = doc["_seq"]["tasks"]
            rec = {"id": tid, "topic_id": topic_id, "time_span_hours": time_span_hours,
                   "deadline": _iso(deadline), "custom_prompt": custom_prompt, "tz_offset": tz_offset,
                   "status": status, "error_message": error_message, "created_at": _now_naive(),
                   "started_at": _iso(started_at), "completed_at": _iso(completed_at)}
            doc["tasks"][str(tid)] = rec
            atomic_write_doc(self._path, doc)
            return self._to_task_domain(doc, rec)

    async def get_task(self, task_id) -> TopicSummaryTaskDomain | None:
        doc = self._load()
        rec = doc["tasks"].get(str(task_id))
        return self._to_task_domain(doc, rec) if rec is not None else None

    async def list_tasks(self, topic_id=None, user_id=None) -> list[TopicSummaryTaskDomain]:
        doc = self._load()
        recs = list(doc["tasks"].values())
        if topic_id is not None:
            recs = [r for r in recs if r["topic_id"] == topic_id]
        if user_id is not None:                  # 跨集合 join:task → 其 topic.user_id
            recs = [r for r in recs
                    if (doc["topics"].get(str(r["topic_id"])) or {}).get("user_id") == user_id]
        recs.sort(key=lambda r: r["created_at"], reverse=True)     # created_at DESC
        return [self._to_task_domain(doc, r) for r in recs]

    async def update_task(self, task: TopicSummaryTaskDomain) -> TopicSummaryTaskDomain:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["tasks"].get(str(task.id))
            if rec is None:                      # 防御:旧 repo 假设存在,parity 不测
                raise NotFoundError(f"任务不存在: {task.id}")
            # 覆盖可变字段(topic_id 不可变;tz_offset 不在域→不动;topic_name/summary 派生→忽略)
            rec["time_span_hours"] = task.time_span_hours
            rec["deadline"] = _iso(task.deadline)
            rec["custom_prompt"] = task.custom_prompt
            rec["status"] = task.status.value
            rec["error_message"] = task.error_message
            rec["started_at"] = _iso(task.started_at)
            rec["completed_at"] = _iso(task.completed_at)
            atomic_write_doc(self._path, doc)
            return self._to_task_domain(doc, rec)

    async def delete_task(self, task_id) -> bool:
        async with shard_lock(self._path):
            doc = self._load()
            if str(task_id) not in doc["tasks"]:
                return False
            del doc["tasks"][str(task_id)]
            # 契约面内级联删其 summary
            doc["summaries"] = {k: s for k, s in doc["summaries"].items() if s["task_id"] != task_id}
            atomic_write_doc(self._path, doc)
            return True

    async def get_latest_completed_task(self, topic_id) -> TopicSummaryTaskDomain | None:
        doc = self._load()
        recs = [r for r in doc["tasks"].values()
                if r["topic_id"] == topic_id and r["status"] == "completed"]
        if not recs:
            return None
        # completed_at DESC limit 1;None 排最后(镜像 sqlite DESC NULL-last)
        recs.sort(key=lambda r: (r["completed_at"] is not None, r["completed_at"] or ""), reverse=True)
        return self._to_task_domain(doc, recs[0])

    # —— 摘要结果 ——
    async def create_summary(self, task_id, content, llm_provider, llm_model,
                             prompt_tokens=0, completion_tokens=0, total_tokens=0,
                             cost_usd=0.0, tweet_count=0, account_count=0,
                             metadata_json=None) -> TopicSummaryDomain:
        async with shard_lock(self._path):
            doc = self._load()
            for s in doc["summaries"].values():        # 手动唯一性:task_id 一对一
                if s["task_id"] == task_id:
                    raise DuplicateError(f"摘要已存在: task_id={task_id}")
            doc["_seq"]["summaries"] = int(doc["_seq"]["summaries"]) + 1
            sid = doc["_seq"]["summaries"]
            rec = {"id": sid, "task_id": task_id, "content": content,
                   "llm_provider": llm_provider, "llm_model": llm_model,
                   "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                   "total_tokens": total_tokens, "cost_usd": cost_usd,
                   "tweet_count": tweet_count, "account_count": account_count,
                   "created_at": _now_naive(),
                   "metadata_json": metadata_json if metadata_json is not None else {}}
            doc["summaries"][str(sid)] = rec
            atomic_write_doc(self._path, doc)
            return TopicSummaryDomain(**rec)

    async def get_summary_by_task(self, task_id) -> TopicSummaryDomain | None:
        s = self._summary_rec_of(self._load(), task_id)
        return TopicSummaryDomain(**s) if s is not None else None

    # —— case 用:完整级联(委派 FileTopicStore.delete)——
    async def delete_topic(self, topic_id) -> bool:
        return await self._topic.delete(topic_id)
