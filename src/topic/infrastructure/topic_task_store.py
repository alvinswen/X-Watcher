"""TopicTaskStore 契约(8 方法 + seed + delete_topic)+ 异常。两实现共享:oracle(vendored 旧 repo)与文件 candidate。

组合 facade:runner 给 case fn 单个 store,delete topic 完整级联验证需同一 store 既 delete_topic 又 get_task。
参数式接口(非传 ORM);返回域模型。
异常面:parity 零自定义异常(全返回值对比);DuplicateError 是文件层 changed(task_id 唯一,出 parity 入 invariant)。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.topic.domain.models import TopicSummaryDomain, TopicSummaryTaskDomain


class RepositoryError(Exception):
    """仓库操作错误。"""


class NotFoundError(RepositoryError):
    """资源未找到(candidate update_task 防御用,parity 不测)。"""


class DuplicateError(RepositoryError):
    """唯一性冲突(create_summary task_id 文件层手动强制,changed,出 parity 入 invariant)。"""


@runtime_checkable
class TopicTaskStore(Protocol):
    # —— 摘要任务 ——
    async def create_task(self, topic_id: int, time_span_hours: int, deadline: datetime,
                          custom_prompt: str | None = None, tz_offset: int = 0,
                          status: str = "pending", error_message: str | None = None,
                          started_at: datetime | None = None,
                          completed_at: datetime | None = None) -> TopicSummaryTaskDomain: ...
    async def get_task(self, task_id: int) -> TopicSummaryTaskDomain | None: ...
    async def list_tasks(self, topic_id: int | None = None,
                         user_id: int | None = None) -> list[TopicSummaryTaskDomain]: ...
    async def update_task(self, task: TopicSummaryTaskDomain) -> TopicSummaryTaskDomain: ...
    async def delete_task(self, task_id: int) -> bool: ...
    async def get_latest_completed_task(self, topic_id: int) -> TopicSummaryTaskDomain | None: ...
    # —— 摘要结果 ——
    async def create_summary(self, task_id: int, content: str, llm_provider: str, llm_model: str,
                             prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0,
                             cost_usd: float = 0.0, tweet_count: int = 0, account_count: int = 0,
                             metadata_json: dict | None = None) -> TopicSummaryDomain: ...
    async def get_summary_by_task(self, task_id: int) -> TopicSummaryDomain | None: ...
    # —— case 用(非契约方法)——
    async def seed(self, topics, tasks=None, summaries=None) -> None: ...
    async def delete_topic(self, topic_id: int) -> bool: ...
