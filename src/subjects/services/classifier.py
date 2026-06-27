"""Subject 在线分类接入。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.data_layer.provider import get_subject_repo
from src.subjects.models import SubjectMatch

logger = logging.getLogger(__name__)


class SubjectClassifier:
    """把摘要 LLM 响应里的 subjects 字段落为 SubjectMatch。"""

    def __init__(self, repo=None) -> None:
        self._repo = repo if repo is not None else get_subject_repo()

    async def prompt_subjects(self) -> list[dict[str, str]]:
        subjects = (await self._repo.list_active_subjects())[:20]
        return [
            {
                "subject_id": subject.subject_id,
                "name": subject.name,
                "nl_description": subject.nl_description,
            }
            for subject in subjects
        ]

    async def record_matches(
        self,
        tweet_id: str,
        raw_subjects: list[dict[str, Any]] | None,
    ) -> list[SubjectMatch]:
        if raw_subjects is None:
            logger.info("议题分类为空或解析失败，跳过 match 写入: tweet_id=%s", tweet_id)
            return []

        active = {subject.subject_id for subject in await self._repo.list_active_subjects()}
        now = datetime.now(timezone.utc)
        matches: list[SubjectMatch] = []
        for item in raw_subjects:
            if not isinstance(item, dict):
                continue
            subject_id = str(item.get("subject_id") or "")
            if subject_id not in active:
                continue
            if item.get("relevant") is not True:
                continue
            relevance = item.get("relevance")
            try:
                relevance_value = float(relevance) if relevance is not None else None
            except (TypeError, ValueError):
                relevance_value = None
            matches.append(
                SubjectMatch(
                    subject_id=subject_id,
                    tweet_id=tweet_id,
                    matched_at=now,
                    relevant=True,
                    relevance=relevance_value,
                    reason=str(item.get("reason") or "")[:240] or None,
                )
            )
        return await self._repo.upsert_matches(matches)
