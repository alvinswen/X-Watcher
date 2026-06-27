"""Subject 议题领域模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SubjectStatus(str, Enum):
    active = "active"
    paused = "paused"


class Subject(BaseModel):
    subject_id: str = Field(..., description="议题内部 ID")
    name: str = Field(..., min_length=1, max_length=120, description="议题显示名")
    nl_description: str = Field(..., min_length=1, description="语义匹配描述")
    keywords: list[str] = Field(default_factory=list, description="展示标签")
    status: SubjectStatus = Field(default=SubjectStatus.active, description="议题状态")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    last_updated_at: datetime | None = Field(None, description="最近 match/digest 更新时间")
    backfill_task_id: str | None = Field(None, description="最近一次回填任务 ID")


class SubjectMatch(BaseModel):
    subject_id: str
    tweet_id: str
    matched_at: datetime
    relevant: bool = True
    relevance: float | None = None
    reason: str | None = None


class SubjectHighlight(BaseModel):
    point: str
    cited_tweet_ids: list[str] = Field(default_factory=list)


class SubjectDigest(BaseModel):
    subject_id: str
    hour: str
    tweet_count: int = 0
    digest_text: str = ""
    highlights: list[SubjectHighlight] = Field(default_factory=list)
    cited_tweet_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    generated_by: str = Field(default="fallback", description="llm 或 fallback")
