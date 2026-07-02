"""Subject 派生物 provenance 校验与组装。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src.subjects.models import Provenance

VALIDATOR_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_IDS_INLINE_MAX = 200
_REQUIRED_FIELDS = (
    "playbook_id",
    "playbook_version",
    "prompt_hash",
    "candidate_set_hash",
)


def is_valid_sha256(s: str) -> bool:
    return bool(_SHA256_RE.match(s))


def _ordered_candidate_ids(tweet_ids: Sequence[str]) -> list[str]:
    return sorted({tid for tid in tweet_ids if tid})


def build_candidate_set_hash(tweet_ids: Sequence[str]) -> str:
    ordered = _ordered_candidate_ids(tweet_ids)
    return hashlib.sha256(",".join(ordered).encode("utf-8")).hexdigest()


def assemble_provenance(
    *,
    raw: Mapping[str, Any],
    recomputed_ids: Sequence[str],
    generated_at: datetime,
) -> Provenance:
    for field in _REQUIRED_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"溯源缺必填字段: {field}")

    prompt_hash = raw["prompt_hash"]
    candidate_set_hash = raw["candidate_set_hash"]
    if not is_valid_sha256(prompt_hash):
        raise ValueError("prompt_hash 需为 64 位小写十六进制 sha256 串")
    if not is_valid_sha256(candidate_set_hash):
        raise ValueError("candidate_set_hash 需为 64 位小写十六进制 sha256 串")

    system_hash = build_candidate_set_hash(recomputed_ids)
    if system_hash != candidate_set_hash:
        raise ValueError(_hash_mismatch_diag(recomputed_ids, raw))

    ordered = _ordered_candidate_ids(recomputed_ids)
    stored_ids = ordered if len(ordered) <= _CANDIDATE_IDS_INLINE_MAX else None
    return Provenance(
        playbook_id=raw["playbook_id"],
        playbook_version=raw["playbook_version"],
        prompt_hash=prompt_hash,
        candidate_set_hash=candidate_set_hash,
        candidate_ids=stored_ids,
        model_name=_optional_str(raw.get("model_name")),
        model_version=_optional_str(raw.get("model_version")),
        generated_at=generated_at,
        validator_version=VALIDATOR_VERSION,
    )


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value


def _raw_candidate_ids(raw: Mapping[str, Any]) -> list[str]:
    value = raw.get("candidate_ids")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _hash_mismatch_diag(recomputed_ids: Sequence[str], raw: Mapping[str, Any]) -> str:
    system_ids = _ordered_candidate_ids(recomputed_ids)
    sys_hash = build_candidate_set_hash(system_ids)
    skill_ids = _ordered_candidate_ids(_raw_candidate_ids(raw))
    diff_ids = sorted(set(system_ids).symmetric_difference(skill_ids))
    preview = ",".join(system_ids[:5])
    diff_preview = ",".join(diff_ids[:5])
    return (
        f"候选集指纹不符：系统按该产物口径重算得 {len(system_ids)} 条候选"
        f"（hash={sys_hash[:8]}…，示例 id: {preview}），"
        f"你传入 candidate_ids 为 {len(skill_ids)} 条（差异 id: {diff_preview}），"
        "与你传入的 candidate_set_hash 不匹配。请按系统口径重圈候选后重传。"
    )
