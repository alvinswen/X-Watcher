"""Subject REST API schemas。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


SubjectStatusLiteral = Literal["active", "paused"]


class SubjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    nl_description: str = Field(..., min_length=1)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("name", "nl_description")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class SubjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    nl_description: str | None = Field(None, min_length=1)
    keywords: list[str] | None = None
    status: SubjectStatusLiteral | None = None

    @field_validator("name", "nl_description")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class TaskSnapshot(BaseModel):
    task_id: str
    status: str
    progress: dict | None = None
    error: str | None = None
    result: dict | None = None


class SubjectResponse(BaseModel):
    subject_id: str
    name: str
    nl_description: str
    keywords: list[str]
    status: SubjectStatusLiteral
    created_at: datetime
    updated_at: datetime
    last_updated_at: datetime | None = None
    match_count: int = 0
    backfill_task_id: str | None = None
    backfill_task: TaskSnapshot | None = None


class SubjectCreateResponse(SubjectResponse):
    backfill_task_id: str
