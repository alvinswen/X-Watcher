"""主题管理 API 请求和响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import UTCDatetimeModel


# ── 请求模型 ──

class CreateTopicRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)

class UpdateTopicRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None

class SetAccountsRequest(BaseModel):
    usernames: list[str] = Field(..., min_length=1)

class CreateSummaryTaskRequest(BaseModel):
    topic_id: int = Field(..., gt=0)
    time_span_hours: int = Field(..., ge=1, le=720)
    deadline: datetime
    custom_prompt: str | None = Field(default=None, max_length=5000)
    tz_offset: int = Field(default=0, ge=-720, le=840, description="用户时区偏移（分钟），来自 JS getTimezoneOffset()")


# ── 响应模型 ──

class TopicResponse(UTCDatetimeModel):
    id: int
    name: str
    description: str | None
    user_id: int | None = None
    created_at: datetime
    updated_at: datetime

class TopicListItem(UTCDatetimeModel):
    id: int
    name: str
    description: str | None
    user_id: int | None = None
    account_count: int
    created_at: datetime

class AccountResponse(UTCDatetimeModel):
    id: int
    username: str
    added_at: datetime

class TopicDetailResponse(TopicResponse):
    accounts: list[AccountResponse]

class SummaryTaskResponse(UTCDatetimeModel):
    id: int
    topic_id: int
    topic_name: str
    time_span_hours: int
    deadline: datetime
    custom_prompt: str | None
    status: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

class SummaryResponse(UTCDatetimeModel):
    id: int
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

class SummaryTaskDetailResponse(SummaryTaskResponse):
    summary: SummaryResponse | None


class LatestSummaryResponse(UTCDatetimeModel):
    topic_id: int
    topic_name: str
    content: str
    generated_at: datetime
    time_span_hours: int
    deadline: datetime
    tweet_count: int
    account_count: int
    task_id: int


class DefaultPromptResponse(BaseModel):
    prompt: str


class ImagePromptResponse(BaseModel):
    image_prompt: str
    llm_provider: str
    llm_model: str
