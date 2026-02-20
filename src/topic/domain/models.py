"""主题管理领域模型。"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class TopicSummaryTaskStatus(str, Enum):
    """摘要任务状态枚举。"""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TopicDomain(BaseModel):
    """主题基本域模型。"""
    id: int
    name: str
    description: str | None
    user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class TopicWithCountDomain(TopicDomain):
    """带账号数量的主题域模型（列表展示用）。"""
    account_count: int


class TopicAccountDomain(BaseModel):
    """主题账号域模型。"""
    id: int
    topic_id: int
    username: str
    added_at: datetime


class TopicDetailDomain(TopicDomain):
    """主题详情域模型（含账号列表）。"""
    accounts: list[TopicAccountDomain]


class TopicSummaryDomain(BaseModel):
    """摘要结果域模型。"""
    id: int
    task_id: int
    content: str
    llm_provider: str
    llm_model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    tweet_count: int
    account_count: int
    created_at: datetime


class TopicSummaryTaskDomain(BaseModel):
    """摘要任务域模型。"""
    id: int
    topic_id: int
    topic_name: str
    time_span_hours: int
    deadline: datetime
    custom_prompt: str | None
    status: TopicSummaryTaskStatus
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    summary: TopicSummaryDomain | None
