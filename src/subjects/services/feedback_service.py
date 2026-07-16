"""Subject feedback 裁决服务。"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from src.storage import paths
from src.subjects._time import iso_z
from src.subjects.constants import SUBJECT_NOT_FOUND_HINT
from src.subjects.models import (
    FeedbackAuthority,
    FeedbackTargetType,
    FeedbackVerdict,
    SubjectFeedback,
)
from src.subjects.protocol import SubjectRepoProtocol, default_subject_repo
from src.subjects.store import utc_now

_WHO_RE = re.compile(r"^(human|agent):.+$")


def build_feedback_target_id(
    target_type: str | FeedbackTargetType,
    *,
    subject_id: str,
    tweet_id: str | None = None,
    interval_start: str | datetime | None = None,
    time_axis: str | None = None,
    version: int | str | None = None,
) -> str:
    parsed = _parse_target_type(str(target_type))
    if parsed == FeedbackTargetType.match:
        if not tweet_id:
            raise ValueError("match target_id 需要 tweet_id")
        return f"match::{subject_id}::{tweet_id}"
    if parsed == FeedbackTargetType.digest:
        if interval_start is None or not time_axis:
            raise ValueError("digest target_id 需要 interval_start 与 time_axis")
        return f"digest::{subject_id}::{_target_time(interval_start)}::{time_axis}"
    if version is None:
        raise ValueError("review target_id 需要 version")
    return f"review::{subject_id}::{version}"


class SubjectFeedbackService:
    def __init__(self, repo: SubjectRepoProtocol | None = None) -> None:
        repo_factory = default_subject_repo
        self._repo: SubjectRepoProtocol = repo if repo is not None else repo_factory()

    async def put_feedback(
        self,
        *,
        subject_id: str,
        target_type: str,
        target_id: str,
        verdict: str,
        authority: str,
        who: str,
        provenance_key: str | None = None,
        corrected_value: str | None = None,
        note: str | None = None,
        supersedes: str | None = None,
    ) -> SubjectFeedback:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND_HINT)

        parsed_target_type = _parse_target_type(target_type)
        clean_target_id = target_id.strip()
        if not clean_target_id:
            raise ValueError("target_id 不能为空")
        parsed_verdict = _parse_verdict(verdict)
        parsed_authority = _parse_authority(authority)
        _validate_who(who, parsed_authority)

        feedback = SubjectFeedback(
            id=f"fb_{uuid.uuid4().hex[:8]}",
            subject_id=subject_id,
            target_type=parsed_target_type,
            target_id=clean_target_id,
            provenance_key=provenance_key,
            verdict=parsed_verdict,
            authority=parsed_authority,
            who=who,
            note=note,
            corrected_value=_parse_corrected_value(corrected_value),
            supersedes=supersedes,
            when=utc_now(),
        )
        saved = await self._repo.append_feedback(feedback)
        return saved

    async def get_current_feedbacks(
        self,
        *,
        subject_id: str,
        target_id: str | None = None,
        target_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND_HINT)

        parsed_target_type = _parse_target_type(target_type) if target_type is not None else None
        clean_target_id = target_id.strip() if target_id is not None else None
        if clean_target_id == "":
            raise ValueError("target_id 不能为空")

        records = await self._repo.read_feedbacks(subject_id)
        if clean_target_id is not None:
            records = [item for item in records if item.target_id == clean_target_id]
        if parsed_target_type is not None:
            records = [item for item in records if item.target_type == parsed_target_type]

        return _dedupe_current_feedbacks(records)


def _target_time(value: str | datetime) -> str:
    if isinstance(value, datetime):
        return iso_z(value)
    return value


def _parse_target_type(value: str) -> FeedbackTargetType:
    try:
        return FeedbackTargetType(value)
    except ValueError as exc:
        raise ValueError("target_type 只能是 match / digest / review") from exc


def _parse_verdict(value: str) -> FeedbackVerdict:
    try:
        return FeedbackVerdict(value)
    except ValueError as exc:
        raise ValueError("verdict 只能是 reject / accept / correct / off_topic / drift") from exc


def _parse_authority(value: str) -> FeedbackAuthority:
    try:
        return FeedbackAuthority(value)
    except ValueError as exc:
        raise ValueError("authority 只能是 human_correction / agent_selfeval") from exc


def _validate_who(value: str, authority: FeedbackAuthority) -> None:
    if not _WHO_RE.match(value):
        raise ValueError("who 需形如 human:<名> 或 agent:<名>")
    if authority == FeedbackAuthority.human_correction and not value.startswith("human:"):
        raise ValueError("human_correction 的 who 须以 human: 开头")
    if authority == FeedbackAuthority.agent_selfeval and not value.startswith("agent:"):
        raise ValueError("agent_selfeval 的 who 须以 agent: 开头")


def _parse_corrected_value(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("corrected_value 需为合法 JSON 字符串") from exc
    if not isinstance(parsed, dict):
        raise ValueError("corrected_value 需为合法 JSON 对象字符串")
    return parsed


def _dedupe_current_feedbacks(
    records: list[SubjectFeedback],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {item.id: item for item in records}
    superseded_ids = {
        item.supersedes for item in records if item.supersedes and item.supersedes in by_id
    }
    groups: dict[str, list[SubjectFeedback]] = defaultdict(list)
    for item in records:
        groups[item.target_id].append(item)

    current: list[SubjectFeedback] = []
    cycle_targets: list[str] = []
    for target_id, group in groups.items():
        candidates = [item for item in group if item.id not in superseded_ids]
        if not candidates:
            cycle_targets.append(target_id)
            candidates = group
        current.append(max(candidates, key=lambda item: (paths.as_utc(item.when), item.id)))

    current.sort(key=lambda item: (paths.as_utc(item.when), item.target_id, item.id))
    payloads: list[dict[str, Any]] = []
    for item in current:
        payload = item.model_dump(mode="json")
        payload["superseded_from"] = _superseded_chain(item, by_id)
        payloads.append(payload)
    return payloads, cycle_targets


def _superseded_chain(
    item: SubjectFeedback,
    by_id: dict[str, SubjectFeedback],
) -> list[str]:
    chain: list[str] = []
    seen = {item.id}
    next_id = item.supersedes
    while next_id and next_id in by_id and next_id not in seen:
        chain.append(next_id)
        seen.add(next_id)
        next_id = by_id[next_id].supersedes
    return chain
