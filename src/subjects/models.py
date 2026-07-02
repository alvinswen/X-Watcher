"""Subject 议题领域模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SubjectStatus(StrEnum):
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
    pending_classify: bool = Field(default=False, description="是否待外部技能分类")
    pending_review: bool = Field(default=False, description="是否待外部技能综述")


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
    interval_start: datetime
    interval_end: datetime
    time_axis: str = "ingest"
    tweet_count: int = 0
    digest_text: str = ""
    highlights: list[SubjectHighlight] = Field(default_factory=list)
    cited_tweet_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    generated_by: str = Field(default="skill", description="llm、fallback 或 skill")


class SubjectReviewSection(BaseModel):
    title: str
    body: str
    cited_tweet_ids: list[str] = Field(default_factory=list)


class SubjectReviewTrend(BaseModel):
    emerging: list[str] = Field(default_factory=list)
    fading: list[str] = Field(default_factory=list)


class SubjectReview(BaseModel):
    subject_id: str
    version: int
    sections: list[SubjectReviewSection] = Field(default_factory=list)
    trend: SubjectReviewTrend = Field(default_factory=SubjectReviewTrend)
    cited_tweet_ids: list[str] = Field(default_factory=list)
    prev_version: int | None = None
    generated_at: datetime
    generated_by: str = Field(default="skill", description="llm、fallback 或 skill")
    updated_at: datetime
    covered_until: datetime | None = None


class Provenance(BaseModel):
    playbook_id: str
    playbook_version: str
    prompt_hash: str
    candidate_set_hash: str
    candidate_ids: list[str] | None = None
    model_name: str | None = None
    model_version: str | None = None
    generated_at: datetime
    validator_version: str | None = None


class FeedbackTargetType(StrEnum):
    match = "match"
    digest = "digest"
    review = "review"


class FeedbackVerdict(StrEnum):
    reject = "reject"
    accept = "accept"
    correct = "correct"
    off_topic = "off_topic"
    drift = "drift"


class FeedbackAuthority(StrEnum):
    human_correction = "human_correction"
    agent_selfeval = "agent_selfeval"


class SubjectFeedback(BaseModel):
    id: str
    subject_id: str
    target_type: FeedbackTargetType
    target_id: str
    provenance_key: str | None = None
    verdict: FeedbackVerdict
    authority: FeedbackAuthority
    who: str
    note: str | None = None
    corrected_value: dict[str, Any] | None = None
    supersedes: str | None = None
    when: datetime


class EvalTier(StrEnum):
    hygiene = "hygiene"
    judge = "judge"
    human = "human"


class SubjectEval(BaseModel):
    id: str
    subject_id: str
    target_id: str
    target_provenance_ref: str | None = None
    tier: EvalTier
    scores: dict[str, float] = Field(default_factory=dict)
    hard_fail: bool | None = None
    failed_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rubric_version: str | None = None
    judge_model: str | None = None
    judge_human_kappa: float | None = Field(default=None, ge=-1, le=1)
    note: str | None = None
    when: datetime
