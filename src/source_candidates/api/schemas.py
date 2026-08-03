"""信源候选管理 REST API 模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CandidateSummaryResponse(BaseModel):
    """队列摘要行（服务层摘要 12 键 + 档案投影 3 键）。"""

    candidate_id: str
    username: str
    platform_user_id: str | None
    status: str
    citation_total: int
    source_diversity: int
    subject_tags: list[str]
    first_discovered_at: str
    last_mined_at: str
    sample_fetched_at: str | None
    assessed_at: str | None
    decided_at: str | None
    display_name: str | None
    verified_type: str | None
    is_automated: bool | None


class CandidateListResponse(BaseModel):
    """候选队列分页响应。"""

    candidates: list[CandidateSummaryResponse]
    count: int
    total: int
    page: int
    page_size: int


class CandidateReviewRequest(BaseModel):
    """终审决策请求。"""

    decision: Literal["approve", "reject"]
    brief_intro: str | None = Field(None, max_length=50)
    reject_reason: str | None = Field(None, max_length=500)


class CandidateReviewResponse(BaseModel):
    """终审决策响应。"""

    candidate_id: str
    status: str
    follow_id: int | None = None
    follow_username: str | None = None
    platform_user_id: str | None = None
    notice: str | None = None
