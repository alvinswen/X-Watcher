"""topic 单元迁移:topics + topic_accounts + topic_summary_tasks + topic_summaries
→ 同一个 topics.json(4 集合一次落盘)。

关键(与计划范式不符,以源码为准):
- **没有单个 seed 收全 4 集合**:FileTopicStore.seed=topics+accounts;
  FileTopicSummaryTaskStore.seed=topics+tasks+summaries(accounts 写空 {})。
  做法:先 task_store.seed(topics,tasks,summaries) 写三集合,再把 accounts 直接补进 doc
  + _seq.accounts(accounts 序列化与 FileTopicStore.seed 完全一致:str(id)->model_dump(json))。
- task 的 topic_name/summary 是派生字段(ORM 无 topic_name 列;_task_to_rec 落盘时 pop 掉);
  构造域对象时 topic_name 从 topic_id→name 映射取(落盘被 pop,值仅供 read 回填一致)。
- tz_offset 在 ORM 但不在域:_task_to_rec 恒写 0 → 若 pg 有非 0 值则文件层不保留(dropped 标注)。
- 时间戳均 DateTime(无 tz)=naive,naive() 幂等透传。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.topic.domain.models import (
    TopicAccountDomain,
    TopicDomain,
    TopicSummaryDomain,
    TopicSummaryTaskDomain,
)
from src.topic.infrastructure.file_topic_repository import FileTopicStore
from src.topic.infrastructure.file_topic_summary_task_repository import (
    FileTopicSummaryTaskStore,
    _task_to_rec,
)
from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
)


def _topic_to_domain(o: TopicOrm) -> TopicDomain:
    return TopicDomain(
        id=o.id, name=o.name, description=o.description, user_id=o.user_id,
        created_at=naive(o.created_at), updated_at=naive(o.updated_at),
    )


def _account_to_domain(o: TopicAccountOrm) -> TopicAccountDomain:
    return TopicAccountDomain(
        id=o.id, topic_id=o.topic_id, username=o.username, added_at=naive(o.added_at),
    )


def _task_to_domain(o: TopicSummaryTaskOrm, topic_name: str) -> TopicSummaryTaskDomain:
    return TopicSummaryTaskDomain(
        id=o.id, topic_id=o.topic_id, topic_name=topic_name,
        time_span_hours=o.time_span_hours, deadline=naive(o.deadline),
        custom_prompt=o.custom_prompt, status=o.status, error_message=o.error_message,
        created_at=naive(o.created_at), started_at=naive(o.started_at),
        completed_at=naive(o.completed_at), summary=None,
    )


def _summary_to_domain(o: TopicSummaryOrm) -> TopicSummaryDomain:
    return TopicSummaryDomain(
        id=o.id, task_id=o.task_id, content=o.content, llm_provider=o.llm_provider,
        llm_model=o.llm_model, prompt_tokens=o.prompt_tokens,
        completion_tokens=o.completion_tokens, total_tokens=o.total_tokens,
        cost_usd=o.cost_usd, tweet_count=o.tweet_count, account_count=o.account_count,
        created_at=naive(o.created_at), metadata_json=o.metadata_json or {},
    )


@register("topic")
async def migrate_topic(session, data_root: Path) -> MigrationReport:
    topic_rows = (await session.execute(select(TopicOrm))).scalars().all()
    account_rows = (await session.execute(select(TopicAccountOrm))).scalars().all()
    task_rows = (await session.execute(select(TopicSummaryTaskOrm))).scalars().all()
    summary_rows = (await session.execute(select(TopicSummaryOrm))).scalars().all()

    pg_count = len(topic_rows) + len(account_rows) + len(task_rows) + len(summary_rows)
    rep = MigrationReport(entity="topic", pg_count=pg_count)
    if any(o.tz_offset != 0 for o in task_rows):
        rep.dropped_columns.append("topic_summary_tasks.tz_offset")

    name_by_id = {o.id: o.name for o in topic_rows}
    topics = [_topic_to_domain(o) for o in topic_rows]
    accounts = [_account_to_domain(o) for o in account_rows]
    tasks = [_task_to_domain(o, name_by_id.get(o.topic_id, "")) for o in task_rows]
    summaries = [_summary_to_domain(o) for o in summary_rows]

    topic_store = FileTopicStore(data_root)
    task_store = FileTopicSummaryTaskStore(data_root)
    path = task_store._path
    path.unlink(missing_ok=True)

    # 1) 三集合(topics/tasks/summaries)经 task_store.seed 落盘(accounts 写空)
    await task_store.seed(topics, tasks, summaries)
    # 2) accounts 补进同一 doc(序列化与 FileTopicStore.seed 一致)+ _seq.accounts
    async with shard_lock(path):
        doc = read_doc(path)
        doc["accounts"] = {str(a.id): a.model_dump(mode="json") for a in accounts}
        doc["_seq"]["accounts"] = max((a.id for a in accounts), default=0)
        atomic_write_doc(path, doc)

    disk = read_doc(path)
    rep.written = (len(disk["topics"]) + len(disk["accounts"])
                   + len(disk["tasks"]) + len(disk["summaries"]))

    # 校验①:落盘记录 == 各自 seed 序列化器(byte-faithful,守"覆盖丢集合"风险)
    rep.validated = 0
    for t in topics:
        if disk["topics"].get(str(t.id)) == t.model_dump(mode="json"):
            rep.validated += 1
        else:
            rep.mismatches.append(f"topic id={t.id}: disk rec != source")
    for a in accounts:
        if disk["accounts"].get(str(a.id)) == a.model_dump(mode="json"):
            rep.validated += 1
        else:
            rep.mismatches.append(f"topic_account id={a.id}: disk rec != source")
    for tk in tasks:
        if disk["tasks"].get(str(tk.id)) == _task_to_rec(tk):
            rep.validated += 1
        else:
            rep.mismatches.append(f"topic_task id={tk.id}: disk rec != source")
    for s in summaries:
        if disk["summaries"].get(str(s.id)) == s.model_dump(mode="json"):
            rep.validated += 1
        else:
            rep.mismatches.append(f"topic_summary id={s.id}: disk rec != source")

    # 校验②:经 store 读法反序列化回域(守 read 路径)— 失败追加 mismatch
    for t in topics:
        td = await topic_store.get_by_id(t.id)
        if td is None or td.id != t.id or td.name != t.name:
            rep.mismatches.append(f"topic get_by_id id={t.id}: readback domain mismatch")
    for t in topics:
        back_accs = {a.id for a in await topic_store.get_accounts(t.id)}
        want_accs = {a.id for a in accounts if a.topic_id == t.id}
        if back_accs != want_accs:
            rep.mismatches.append(f"topic get_accounts topic_id={t.id}: {back_accs} != {want_accs}")
    for tk in tasks:
        back = await task_store.get_task(tk.id)
        if back is None or _task_to_rec(back) != _task_to_rec(tk):
            rep.mismatches.append(f"topic get_task id={tk.id}: readback domain mismatch")

    return rep
