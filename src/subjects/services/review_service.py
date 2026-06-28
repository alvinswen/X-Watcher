"""Subject L2 活综述读取服务。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from src.data_layer.provider import get_subject_repo


class SubjectReviewService:
    def __init__(self, repo: Any | None = None, providers: list[Any] | None = None) -> None:
        repo_factory = cast(Callable[[], Any], get_subject_repo)
        self._repo: Any = repo if repo is not None else repo_factory()
        self._providers: list[Any] | None = providers

    async def get_review_payload(self, subject_id: str) -> dict[str, Any] | None:
        if await self._repo.get_subject(subject_id) is None:
            return None
        stored = await self._repo.get_review(subject_id)
        if stored is None:
            return self.empty_review_payload(subject_id)
        payload: dict[str, Any] = stored.model_dump(mode="json")
        return payload

    @staticmethod
    def empty_review_payload(subject_id: str) -> dict[str, Any]:
        return {
            "subject_id": subject_id,
            "version": 0,
            "sections": [],
            "trend": {"emerging": [], "fading": []},
            "cited_tweet_ids": [],
            "prev_version": None,
            "generated_at": None,
            "generated_by": None,
            "updated_at": None,
        }
