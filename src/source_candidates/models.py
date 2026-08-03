"""信源候选域模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("候选域时间必须带时区")
    return value


class CandidateStatus(StrEnum):
    DISCOVERED = "discovered"
    ASSESSED = "assessed"
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in {self.APPROVED, self.REJECTED}


class CitationSignal(BaseModel):
    count: int = 0
    citing_tweet_ids: list[str] = Field(default_factory=list)


class MiningSignal(BaseModel):
    citations: dict[str, CitationSignal] = Field(default_factory=dict)
    citation_total: int = 0
    source_diversity: int = 0
    sample_citation_tweet_ids: list[str] = Field(default_factory=list)
    subject_tags: list[str] = Field(default_factory=list)
    first_discovered_at: datetime
    last_mined_at: datetime

    _aware_times = field_validator("first_discovered_at", "last_mined_at")(_require_aware)


class CandidateSample(BaseModel):
    tweets: list[dict[str, Any]] = Field(default_factory=list)
    fetched_at: datetime

    _aware_time = field_validator("fetched_at")(_require_aware)


class CandidateScores(BaseModel):
    originality: int = Field(ge=0, le=10)
    difference: int = Field(ge=0, le=10)
    expertise: int = Field(ge=0, le=10)


class CandidateAssessment(BaseModel):
    scores: CandidateScores
    recommendation: str
    evidence_tweet_ids: list[str]
    assessed_at: datetime
    assessed_by: str

    _aware_time = field_validator("assessed_at")(_require_aware)


class CandidateDecision(BaseModel):
    verdict: str
    decided_by: str
    decided_at: datetime
    reject_reason: str | None = None
    follow_id: int | None = None
    follow_username: str | None = None

    _aware_time = field_validator("decided_at")(_require_aware)


class SourceCandidate(BaseModel):
    candidate_id: str
    username: str
    platform_user_id: str | None = None
    status: CandidateStatus = CandidateStatus.DISCOVERED
    mining: MiningSignal
    profile_snapshot: dict[str, Any] | None = None
    profile_fetched_at: datetime | None = None
    sample: CandidateSample | None = None
    assessment: CandidateAssessment | None = None
    decision: CandidateDecision | None = None

    _aware_profile_time = field_validator("profile_fetched_at")(_require_aware)
