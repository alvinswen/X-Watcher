"""Subject 在线分类接入。"""

from __future__ import annotations

from typing import Any

from src.data_layer.provider import get_subject_repo
from src.subjects.models import SubjectMatch
from src.subjects.provenance import assemble_provenance
from src.subjects.store import utc_now


class SubjectClassifier:
    """提供议题 prompt 元数据，供后续外部技能复用。"""

    def __init__(self, repo: Any | None = None) -> None:
        repo_factory = get_subject_repo
        self._repo: Any = repo if repo is not None else repo_factory()

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

    async def write_matches(
        self,
        *,
        subject_id: str,
        tweet_ids: list[str],
        relevance: float | None = None,
        reason: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError("议题不存在")
        ids = list(dict.fromkeys([tweet_id.strip() for tweet_id in tweet_ids if tweet_id.strip()]))
        if not ids:
            raise ValueError("tweet_ids 不能为空")
        _items, missing = await self._repo.get_tweets_by_ids(ids)
        if missing:
            raise ValueError(f"引用悬空 missing_ids={missing}")
        matched_at = utc_now()
        prov = (
            assemble_provenance(
                raw=provenance,
                recomputed_ids=ids,
                generated_at=matched_at,
            )
            if provenance is not None
            else None
        )
        matches = [
            SubjectMatch(
                subject_id=subject_id,
                tweet_id=tweet_id,
                matched_at=matched_at,
                relevance=relevance,
                reason=reason,
            )
            for tweet_id in ids
        ]
        saved = await self._repo.upsert_matches(matches)
        await self._repo.set_pending(subject_id, classify=False)
        data: dict[str, Any] = {
            "written": len(saved),
            "subject_id": subject_id,
            "pending_classify": False,
        }
        if prov is not None:
            try:
                await self._repo.save_provenance(
                    subject_id=subject_id,
                    kind="matches",
                    key=prov.candidate_set_hash,
                    provenance=prov,
                )
                data["provenance_written"] = True
                data["provenance_key"] = prov.candidate_set_hash
            except OSError:
                data["provenance_written"] = False
        return data
