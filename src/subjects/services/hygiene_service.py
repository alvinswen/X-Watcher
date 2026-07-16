"""Subject 派生物卫生体检服务。"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from src.data_layer.provider import get_subject_repo
from src.storage import paths
from src.subjects._time import iso_z as _iso_z
from src.subjects._time import parse_dt as _parse_dt
from src.subjects.constants import NO_LIMIT, SUBJECT_NOT_FOUND_HINT
from src.subjects.models import EvalTier, SubjectDigest, SubjectEval, SubjectReview
from src.subjects.provenance import build_digest_provenance_key
from src.subjects.services.digest_service import MAX_DIGEST_TEXT
from src.subjects.services.feedback_service import build_feedback_target_id
from src.subjects.services.review_service import MAX_SECTION_BODY
from src.subjects.store import utc_now

_SHINGLE_LEN = 20
_COLLAPSE_MIN_CITED = 3
class SubjectHygieneService:
    def __init__(self, repo: Any | None = None) -> None:
        repo_factory = get_subject_repo
        self._repo: Any = repo if repo is not None else repo_factory()

    async def run_check(
        self,
        *,
        subject_id: str,
        target_type: str,
        interval_start: str | datetime | None = None,
        time_axis: str | None = None,
        generated_at: str | datetime | None = None,
        version: int | None = None,
    ) -> dict[str, Any]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND_HINT)
        if target_type == "match":
            raise ValueError(
                "match 不支持卫生计算，match 质量信号请调 get_subject_correction_rate 人工更正率"
            )
        if target_type not in {"digest", "review"}:
            raise ValueError("target_type 只能是 digest / review")

        if target_type == "digest":
            located = await self._locate_digest(
                subject_id=subject_id,
                interval_start=interval_start,
                time_axis=time_axis,
                generated_at=generated_at,
            )
            record = located["record"]
            candidate_ids, target_ref, basis_warnings = await self._digest_basis(record)
            target_id = build_feedback_target_id(
                "digest",
                subject_id=subject_id,
                interval_start=record.interval_start,
                time_axis=record.time_axis,
            )
            cited = _dedup(
                [*record.cited_tweet_ids]
                + [
                    tweet_id
                    for highlight in record.highlights
                    for tweet_id in highlight.cited_tweet_ids
                ]
            )
            body_length = len(record.digest_text)
            text = record.digest_text
            length_limit = MAX_DIGEST_TEXT
            located_payload = {
                "target_type": "digest",
                "interval_start": _iso_z(record.interval_start),
                "interval_end": _iso_z(record.interval_end),
                "time_axis": record.time_axis,
                "generated_at": _iso_z(record.generated_at),
                "candidates_in_coordinate": located["candidates_in_coordinate"],
            }
        else:
            located = await self._locate_review(subject_id=subject_id, version=version)
            record = located["record"]
            candidate_ids, target_ref, basis_warnings = await self._review_basis(record)
            target_id = build_feedback_target_id(
                "review",
                subject_id=subject_id,
                version=record.version,
            )
            cited = _dedup(
                [*record.cited_tweet_ids]
                + [tweet_id for section in record.sections for tweet_id in section.cited_tweet_ids]
            )
            body_length = max((len(section.body) for section in record.sections), default=0)
            text = "\n".join(section.body for section in record.sections)
            length_limit = MAX_SECTION_BODY
            located_payload = {
                "target_type": "review",
                "version": record.version,
                "candidates_in_coordinate": 1,
            }

        scores, failed_checks, warnings = await self._score(
            cited=cited,
            candidate_ids=candidate_ids,
            body_length=body_length,
            body_limit=length_limit,
            text=text,
        )
        for warning in basis_warnings:
            _add_once(warnings, warning)
        for warning in located.get("warnings", []):
            _add_once(warnings, warning)

        eval_record = SubjectEval(
            id=f"ev_{uuid.uuid4().hex[:8]}",
            subject_id=subject_id,
            target_id=target_id,
            target_provenance_ref=target_ref,
            tier=EvalTier.hygiene,
            scores=scores,
            hard_fail=bool(failed_checks),
            failed_checks=failed_checks,
            warnings=warnings,
            when=utc_now(),
        )
        saved = await self._repo.append_eval(eval_record)
        return {
            "eval": cast(SubjectEval, saved).model_dump(mode="json"),
            "located": located_payload,
        }

    async def _locate_digest(
        self,
        *,
        subject_id: str,
        interval_start: str | datetime | None,
        time_axis: str | None,
        generated_at: str | datetime | None,
    ) -> dict[str, Any]:
        if interval_start is None:
            raise ValueError("digest 体检需要 interval_start")
        if time_axis not in {"ingest", "publish"}:
            raise ValueError("time_axis 只能是 ingest 或 publish")
        start = _parse_dt(interval_start)
        digests = [
            digest
            for digest in await self._repo.list_digests(subject_id, limit=NO_LIMIT)
            if paths.as_utc(digest.interval_start) == start and digest.time_axis == time_axis
        ]
        if not digests:
            raise LookupError("该区间无 digest 产物")
        if generated_at is not None:
            generated = _parse_dt(generated_at)
            digests = [
                digest for digest in digests if paths.as_utc(digest.generated_at) == generated
            ]
            if not digests:
                raise LookupError("该 generated_at 无匹配 digest 产物")
        warnings: list[str] = []
        if generated_at is None and len(digests) > 1:
            warnings.append("multiple_in_interval")
        record = max(digests, key=lambda item: paths.as_utc(item.generated_at))
        return {
            "record": record,
            "candidates_in_coordinate": len(digests),
            "warnings": warnings,
        }

    async def _locate_review(self, *, subject_id: str, version: int | None) -> dict[str, Any]:
        if version is None:
            review = await self._repo.get_review(subject_id)
            if review is None or review.version == 0:
                raise LookupError("该议题尚无综述")
            return {"record": review, "warnings": []}
        for review in await self._repo.list_review_history(subject_id):
            if review.version == version:
                return {"record": review, "warnings": []}
        raise LookupError("该版本无 review 产物")

    async def _digest_basis(
        self,
        digest: SubjectDigest,
    ) -> tuple[list[str], str | None, list[str]]:
        key = build_digest_provenance_key(
            digest.interval_start,
            digest.time_axis,
            digest.generated_at,
        )
        provenance = await self._repo.read_provenance(
            subject_id=digest.subject_id,
            kind="digests",
            key=key,
        )
        if provenance is not None and provenance.candidate_ids is not None:
            return list(provenance.candidate_ids), key, []

        warnings = ["basis_recomputed_now"]
        if provenance is None:
            warnings.insert(0, "no_provenance_doc")
        if digest.time_axis == "publish":
            matches = await self._repo.publish_window_matches(
                digest.subject_id,
                start=digest.interval_start,
                end=digest.interval_end,
            )
        else:
            matches = await self._repo.list_matches(
                digest.subject_id,
                since=digest.interval_start,
                until=digest.interval_end,
            )
        return (
            [match.tweet_id for match in matches],
            key if provenance is not None else None,
            warnings,
        )

    async def _review_basis(
        self,
        review: SubjectReview,
    ) -> tuple[list[str], str | None, list[str]]:
        key = str(review.version)
        provenance = await self._repo.read_provenance(
            subject_id=review.subject_id,
            kind="review",
            key=key,
        )
        if provenance is not None and provenance.candidate_ids is not None:
            return list(provenance.candidate_ids), key, []

        warnings = ["basis_recomputed_now"]
        if provenance is None:
            warnings.insert(0, "no_provenance_doc")
        matches = await self._repo.list_matches(review.subject_id)
        return (
            [match.tweet_id for match in matches],
            key if provenance is not None else None,
            warnings,
        )

    async def _score(
        self,
        *,
        cited: list[str],
        candidate_ids: list[str],
        body_length: int,
        body_limit: int,
        text: str,
    ) -> tuple[dict[str, float], list[str], list[str]]:
        candidate_set = set(candidate_ids)
        cited_set = set(cited)
        valid_cited = cited_set & candidate_set
        author_ids, missing_tweets = await self._repo.get_tweet_author_ids(cited)
        missing_author_id = [
            tweet_id
            for tweet_id in cited
            if tweet_id not in missing_tweets and author_ids.get(tweet_id) is None
        ]
        resolved_authors = [
            author_id for tweet_id in cited if (author_id := author_ids.get(tweet_id)) is not None
        ]

        scores: dict[str, float] = {
            "cited_count": float(len(cited)),
            "missing_cited_count": float(len(missing_tweets)),
            "missing_author_id_count": float(len(missing_author_id)),
            "candidate_count": float(len(candidate_set)),
            "max_body_length": float(body_length),
            "duplicate_rate": _duplicate_rate(text),
        }
        failed_checks: list[str] = []
        warnings: list[str] = []

        if missing_tweets:
            _add_once(warnings, "cited_tweets_missing")
        if missing_author_id:
            _add_once(warnings, "author_id_unresolved")
        if len(resolved_authors) < _COLLAPSE_MIN_CITED:
            _add_once(warnings, "citations_below_min")

        if candidate_set:
            if cited:
                cited_valid_rate = len(valid_cited) / len(cited)
                scores["cited_valid_rate"] = cited_valid_rate
                if cited_valid_rate < 1:
                    failed_checks.append("cited_out_of_basis")
            scores["coverage_rate"] = len(valid_cited) / len(candidate_set)
        else:
            _add_once(warnings, "candidate_set_empty")

        if resolved_authors:
            counts = Counter(resolved_authors)
            total = len(resolved_authors)
            scores["source_hhi"] = sum((count / total) ** 2 for count in counts.values())
            scores["source_count"] = float(len(counts))
            if total >= _COLLAPSE_MIN_CITED and len(counts) == 1:
                failed_checks.append("source_collapse")

        if body_length > body_limit:
            failed_checks.append("length_exceeded")

        return scores, failed_checks, warnings


def _dedup(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if value]))


def _duplicate_rate(text: str) -> float:
    if len(text) < _SHINGLE_LEN:
        return 0.0
    shingles = [text[index : index + _SHINGLE_LEN] for index in range(len(text) - _SHINGLE_LEN + 1)]
    if not shingles:
        return 0.0
    return 1 - (len(set(shingles)) / len(shingles))


def _add_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
