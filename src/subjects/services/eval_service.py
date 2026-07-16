"""Subject eval 评估账本服务。"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from src.storage import paths
from src.subjects._time import iso_z as _iso_z
from src.subjects._time import parse_dt as _parse_dt
from src.subjects.constants import NO_LIMIT, SUBJECT_NOT_FOUND_HINT
from src.subjects.models import EvalTier, SubjectEval
from src.subjects.protocol import SubjectRepoProtocol, default_subject_repo
from src.subjects.services.feedback_service import build_feedback_target_id
from src.subjects.store import utc_now

_MAX_WINDOW_DAYS = 365
_CORRECTION_VERDICTS = {"reject", "correct", "off_topic", "drift"}


class SubjectEvalService:
    def __init__(self, repo: SubjectRepoProtocol | None = None) -> None:
        repo_factory = default_subject_repo
        self._repo: SubjectRepoProtocol = repo if repo is not None else repo_factory()

    async def put_eval(
        self,
        *,
        subject_id: str,
        target_id: str,
        tier: str,
        scores: str | dict[str, Any] | None = None,
        target_provenance_ref: str | None = None,
        rubric_version: str | None = None,
        judge_model: str | None = None,
        judge_human_kappa: float | None = None,
        note: str | None = None,
    ) -> SubjectEval:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND_HINT)

        parsed_tier = _parse_write_tier(tier)
        clean_target_id = _parse_target_id(target_id)
        clean_rubric_version = _clean_optional_text(rubric_version, "rubric_version")
        clean_judge_model = _clean_optional_text(judge_model, "judge_model")
        if judge_human_kappa is not None and not -1 <= judge_human_kappa <= 1:
            raise ValueError("judge_human_kappa 需在 -1 到 1 之间")

        eval_record = SubjectEval(
            id=f"ev_{uuid.uuid4().hex[:8]}",
            subject_id=subject_id,
            target_id=clean_target_id,
            target_provenance_ref=target_provenance_ref,
            tier=parsed_tier,
            scores=_parse_scores(scores),
            hard_fail=None,
            failed_checks=[],
            warnings=[],
            rubric_version=clean_rubric_version,
            judge_model=clean_judge_model,
            judge_human_kappa=judge_human_kappa,
            note=note,
            when=utc_now(),
        )
        saved = await self._repo.append_eval(eval_record)
        return saved

    async def get_evals(
        self,
        *,
        subject_id: str,
        target_id: str | None = None,
        tier: str | None = None,
        since: str | datetime | None = None,
        until: str | datetime | None = None,
    ) -> dict[str, Any]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND_HINT)

        parsed_tier = _parse_any_tier(tier) if tier is not None else None
        clean_target_id = target_id.strip() if target_id is not None else None
        if clean_target_id == "":
            raise ValueError("target_id 不能为空")
        since_dt = _parse_dt(since) if since is not None else None
        until_dt = _parse_dt(until) if until is not None else None

        evals = await self._repo.read_evals(subject_id)
        if clean_target_id is not None:
            evals = [item for item in evals if item.target_id == clean_target_id]
        if parsed_tier is not None:
            evals = [item for item in evals if item.tier == parsed_tier]
        if since_dt is not None:
            evals = [item for item in evals if paths.as_utc(item.when) >= since_dt]
        if until_dt is not None:
            evals = [item for item in evals if paths.as_utc(item.when) < until_dt]
        evals.sort(key=lambda item: (paths.as_utc(item.when), item.id))
        return {
            "subject_id": subject_id,
            "count": len(evals),
            "evals": [item.model_dump(mode="json") for item in evals],
        }

    async def get_correction_rate(
        self,
        *,
        subject_id: str,
        window_days: int,
    ) -> tuple[dict[str, Any], list[str]]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND_HINT)
        if isinstance(window_days, bool) or not isinstance(window_days, int):
            raise ValueError("window_days 必须是整数")
        if window_days <= 0:
            raise ValueError("window_days 必须在 1 到 365 天之间")
        if window_days > _MAX_WINDOW_DAYS:
            raise ValueError("窗口上限 365 天")

        end = utc_now()
        start = end - timedelta(days=window_days)
        current_feedbacks, cycle_targets = await self._feedback_service().get_current_feedbacks(
            subject_id=subject_id
        )
        corrected_targets = {
            item["target_id"]
            for item in current_feedbacks
            if item.get("authority") == "human_correction"
            and item.get("verdict") in _CORRECTION_VERDICTS
        }

        match_targets = [
            build_feedback_target_id(
                "match",
                subject_id=subject_id,
                tweet_id=match.tweet_id,
            )
            for match in await self._repo.list_matches(subject_id, since=start)
            if paths.as_utc(match.matched_at) <= end
        ]
        digest_targets = [
            build_feedback_target_id(
                "digest",
                subject_id=subject_id,
                interval_start=digest.interval_start,
                time_axis=digest.time_axis,
            )
            for digest in await self._repo.list_digests(subject_id, limit=NO_LIMIT)
            if start <= paths.as_utc(digest.generated_at) <= end
        ]
        review_targets = [
            build_feedback_target_id(
                "review",
                subject_id=subject_id,
                version=review.version,
            )
            for review in await self._repo.list_review_history(subject_id)
            if start <= paths.as_utc(review.generated_at) <= end
        ]

        by_type = {
            "match": _rate_bucket(match_targets, corrected_targets),
            "digest": _rate_bucket(digest_targets, corrected_targets),
            "review": _rate_bucket(review_targets, corrected_targets),
        }
        total_targets = match_targets + digest_targets + review_targets
        data = {
            "subject_id": subject_id,
            "window_days": window_days,
            "window_start": _iso_z(start),
            "window_end": _iso_z(end),
            "by_type": by_type,
            "total": _rate_bucket(total_targets, corrected_targets),
        }
        return data, cycle_targets

    def _feedback_service(self) -> Any:
        from src.subjects.services.feedback_service import SubjectFeedbackService

        return SubjectFeedbackService(self._repo)


def _parse_write_tier(value: str) -> EvalTier:
    if value == EvalTier.hygiene.value:
        raise ValueError("hygiene 档请调 run_subject_hygiene_check 卫生计算工具")
    if value not in {EvalTier.judge.value, EvalTier.human.value}:
        raise ValueError("tier 只能是 judge / human")
    return EvalTier(value)


def _parse_any_tier(value: str) -> EvalTier:
    try:
        return EvalTier(value)
    except ValueError as exc:
        raise ValueError("tier 只能是 hygiene / judge / human") from exc


def _parse_target_id(value: str) -> str:
    clean = value.strip()
    parts = clean.split("::")
    if len(parts) < 3 or parts[0] not in {"match", "digest", "review"}:
        raise ValueError("target_id 格式非法，需为 match/digest/review 双冒号坐标")
    if any(part == "" for part in parts):
        raise ValueError("target_id 格式非法，坐标段不能为空")
    return clean


def _parse_scores(value: str | dict[str, Any] | None) -> dict[str, float]:
    if value is None:
        return {}
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("scores 需为合法 JSON 对象字符串") from exc
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ValueError("scores 需为合法 JSON 对象字符串")
    scores: dict[str, float] = {}
    for key, score in parsed.items():
        if not isinstance(key, str) or not key:
            raise ValueError("scores 的键必须是非空字符串")
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise ValueError("scores 的值必须全为数值")
        scores[key] = float(score)
    return scores


def _clean_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} 不能为空文本")
    return clean


def _rate_bucket(target_ids: list[str], corrected_targets: set[str]) -> dict[str, Any]:
    produced = len(target_ids)
    corrected = sum(
        count for target, count in Counter(target_ids).items() if target in corrected_targets
    )
    return {
        "produced": produced,
        "corrected": corrected,
        "rate": None if produced == 0 else corrected / produced,
        "not_applicable": produced == 0,
    }
