"""Subject L2 活综述读取服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from src.data_layer.provider import get_subject_repo
from src.storage import paths
from src.subjects.models import SubjectReview, SubjectReviewSection, SubjectReviewTrend
from src.subjects.provenance import assemble_provenance
from src.subjects.store import utc_now

_MAX_SECTION_BODY = 4000


class ReviewConflictError(Exception):
    def __init__(self, *, latest_version: int, covered_until: datetime | None) -> None:
        super().__init__("版本冲突，请用最新版本重算")
        self.latest_version = latest_version
        self.covered_until = covered_until


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
            "covered_until": None,
        }

    async def write_review(
        self,
        *,
        subject_id: str,
        prev_version: int,
        sections: list[SubjectReviewSection],
        covered_until: datetime,
        trend: SubjectReviewTrend | None = None,
        cited_tweet_ids: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError("议题不存在")
        current = await self._repo.get_review(subject_id)
        current_version = current.version if current is not None else 0
        if prev_version != current_version:
            raise ReviewConflictError(
                latest_version=current_version,
                covered_until=current.covered_until if current is not None else None,
            )
        if not sections:
            raise ValueError("sections 不能为空")
        for index, section in enumerate(sections, start=1):
            body = section.body.strip()
            if not body:
                raise ValueError(f"第 {index} 段 body 不能为空")
            if len(body) > _MAX_SECTION_BODY:
                raise ValueError(f"第 {index} 段 body 超过 4000 字上限")

        matches = await self._repo.list_matches(subject_id)
        allowed_ids = {match.tweet_id for match in matches}
        cited = list(dict.fromkeys(cited_tweet_ids or []))
        section_cited = [tweet_id for section in sections for tweet_id in section.cited_tweet_ids]
        missing_cited = [
            tweet_id
            for tweet_id in list(dict.fromkeys(cited + section_cited))
            if tweet_id not in allowed_ids
        ]
        if missing_cited:
            raise ValueError(f"cited_tweet_ids 不属于该议题命中: {missing_cited}")

        now = utc_now()
        prov = (
            assemble_provenance(
                raw=provenance,
                recomputed_ids=[match.tweet_id for match in matches],
                generated_at=now,
            )
            if provenance is not None
            else None
        )
        review = SubjectReview(
            subject_id=subject_id,
            version=current_version + 1,
            sections=sections,
            trend=trend or SubjectReviewTrend(),
            cited_tweet_ids=cited,
            prev_version=current_version if current is not None else None,
            generated_at=now,
            updated_at=now,
            covered_until=paths.as_utc(covered_until),
        )
        await self._repo.save_review(review)
        await self._repo.set_pending(subject_id, review=False)
        data: dict[str, Any] = {"subject_id": subject_id, "version": review.version}
        if prov is not None:
            try:
                await self._repo.save_provenance(
                    subject_id=subject_id,
                    kind="review",
                    key=str(review.version),
                    provenance=prov,
                )
                data["provenance_written"] = True
            except OSError:
                data["provenance_written"] = False
        return data
