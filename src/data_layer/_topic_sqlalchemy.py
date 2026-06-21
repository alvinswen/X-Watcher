"""sqlalchemy 模式 topic store adapter:把旧 TopicRepository/TopicSummaryTaskRepository
包成 se TopicStore/TopicTaskStore 协议(返域模型)。

设计:照 se acceptance/oracle/topic_repo.py 的 OracleTopicStore,但 (a) 包旧应用真 repo;
(b) **延迟 commit**——方法只走 repo(repo 自身 flush),不 commit;commit 留给服务方法体,
逐字保 sqlalchemy 多操作原子性(spec §4 方案 A)。
"""
from __future__ import annotations

from src.topic.infrastructure.models import (
    TopicAccountOrm, TopicOrm, TopicSummaryOrm, TopicSummaryTaskOrm,
)
from src.topic.infrastructure.repository import TopicRepository, TopicSummaryTaskRepository


class SqlalchemyTopicStore:
    """TopicStore 协议(11 方法):旧 TopicRepository + ORM↔域转换,延迟 commit。"""

    def __init__(self, session) -> None:
        self._session = session
        self._repo = TopicRepository()

    async def create(self, name, description=None, user_id=None):
        orm = TopicOrm.from_domain(name=name, description=description, user_id=user_id)
        r = await self._repo.create(self._session, orm)          # add + flush
        return r.to_domain()

    async def get_by_id(self, topic_id):
        r = await self._repo.get_by_id(self._session, topic_id)
        return r.to_detail_domain() if r is not None else None

    async def get_by_name(self, name, user_id=None):
        r = await self._repo.get_by_name(self._session, name, user_id)
        return r.to_domain() if r is not None else None

    async def list_all(self, user_id=None):
        rows = await self._repo.list_all(self._session, user_id)
        return [orm.to_domain_with_count(cnt) for orm, cnt in rows]

    async def update(self, topic):                               # topic: TopicDomain(可为 TopicDetailDomain 子类)
        orm = await self._session.get(TopicOrm, topic.id)
        orm.name = topic.name
        orm.description = topic.description
        orm.user_id = topic.user_id
        r = await self._repo.update(self._session, orm)          # flush(onupdate 触发 updated_at)
        return r.to_domain()

    async def delete(self, topic_id):
        return await self._repo.delete(self._session, topic_id)  # select + session.delete + flush

    async def add_account(self, topic_id, username):
        orm = TopicAccountOrm(topic_id=topic_id, username=username)
        r = await self._repo.add_account(self._session, orm)
        return r.to_domain()

    async def get_account(self, topic_id, username):
        r = await self._repo.get_account(self._session, topic_id, username)
        return r.to_domain() if r is not None else None

    async def get_accounts(self, topic_id):
        rs = await self._repo.get_accounts(self._session, topic_id)
        return [a.to_domain() for a in rs]

    async def delete_account(self, topic_id, username):
        return await self._repo.delete_account(self._session, topic_id, username)

    async def replace_accounts(self, topic_id, usernames):
        accounts = [TopicAccountOrm(topic_id=topic_id, username=u) for u in usernames]
        rs = await self._repo.replace_accounts(self._session, topic_id, accounts)
        return [a.to_domain() for a in rs]


class SqlalchemyTopicSummaryTaskStore:
    """TopicTaskStore 协议(8 方法):旧 TopicSummaryTaskRepository + 转换,延迟 commit。"""

    def __init__(self, session) -> None:
        self._session = session
        self._repo = TopicSummaryTaskRepository()

    async def create_task(self, topic_id, time_span_hours, deadline, custom_prompt=None,
                          tz_offset=0, status="pending", error_message=None,
                          started_at=None, completed_at=None):
        orm = TopicSummaryTaskOrm(
            topic_id=topic_id, time_span_hours=time_span_hours, deadline=deadline,
            custom_prompt=custom_prompt, tz_offset=tz_offset, status=status,
            error_message=error_message, started_at=started_at, completed_at=completed_at)
        await self._repo.create_task(self._session, orm)         # add + flush(分配 id)
        await self._session.refresh(orm, ["topic", "summary"])   # 补 topic_name + summary(=None)
        return orm.to_domain()

    async def get_task(self, task_id):
        r = await self._repo.get_task(self._session, task_id)
        return r.to_domain() if r is not None else None

    async def list_tasks(self, topic_id=None, user_id=None):
        rs = await self._repo.list_tasks(self._session, topic_id, user_id=user_id)
        return [t.to_domain() for t in rs]

    async def update_task(self, task):                           # task: TopicSummaryTaskDomain
        orm = await self._session.get(TopicSummaryTaskOrm, task.id)
        orm.time_span_hours = task.time_span_hours
        orm.deadline = task.deadline
        orm.custom_prompt = task.custom_prompt
        orm.status = task.status.value                           # 域 status 是枚举 → 取 .value 入 String 列
        orm.error_message = task.error_message
        orm.started_at = task.started_at
        orm.completed_at = task.completed_at
        await self._repo.update_task(self._session, orm)         # flush
        await self._session.refresh(orm, ["topic", "summary"])
        return orm.to_domain()

    async def delete_task(self, task_id):
        return await self._repo.delete_task(self._session, task_id)

    async def get_latest_completed_task(self, topic_id):
        r = await self._repo.get_latest_completed_task(self._session, topic_id)
        return r.to_domain() if r is not None else None

    async def create_summary(self, task_id, content, llm_provider, llm_model,
                             prompt_tokens=0, completion_tokens=0, total_tokens=0,
                             cost_usd=0.0, tweet_count=0, account_count=0, metadata_json=None):
        orm = TopicSummaryOrm(
            task_id=task_id, content=content, llm_provider=llm_provider, llm_model=llm_model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, cost_usd=cost_usd, tweet_count=tweet_count,
            account_count=account_count, metadata_json=metadata_json if metadata_json is not None else {})
        r = await self._repo.create_summary(self._session, orm)
        return r.to_domain()

    async def get_summary_by_task(self, task_id):
        r = await self._repo.get_summary_by_task(self._session, task_id)
        return r.to_domain() if r is not None else None
