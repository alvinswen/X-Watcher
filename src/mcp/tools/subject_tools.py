"""MCP Subject 议题工具。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from src.data_layer.provider import get_subject_repo
from src.mcp.auth import require_scope
from src.mcp.helpers import error_response, parse_datetime_optional, success_response
from src.mcp.security import audit_log
from src.subjects.models import SubjectHighlight, SubjectReviewSection, SubjectReviewTrend
from src.subjects.provenance import build_candidate_set_hash
from src.subjects.services.classifier import SubjectClassifier
from src.subjects.services.digest_service import SubjectDigestService
from src.subjects.services.eval_service import SubjectEvalService
from src.subjects.services.feedback_service import SubjectFeedbackService
from src.subjects.services.hygiene_service import SubjectHygieneService
from src.subjects.services.review_service import ReviewConflictError, SubjectReviewService

logger = logging.getLogger(__name__)
REVIEW_PENDING_MESSAGE = "综述刷新已加入待综述队列，外部技能将异步处理"
REVIEW_MIGRATED_MESSAGE = "综述生成已迁移至外部技能，全量刷新入口暂不批量挂待办"


def _csv_ids(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _collect_provenance(
    playbook_id: str | None,
    playbook_version: str | None,
    prompt_hash: str | None,
    candidate_set_hash: str | None,
    candidate_ids: str | None,
    model_name: str | None,
    model_version: str | None,
) -> dict[str, Any] | None:
    values = (
        playbook_id,
        playbook_version,
        prompt_hash,
        candidate_set_hash,
        candidate_ids,
        model_name,
        model_version,
    )
    if all(value is None for value in values):
        return None
    return {
        "playbook_id": playbook_id,
        "playbook_version": playbook_version,
        "prompt_hash": prompt_hash,
        "candidate_set_hash": candidate_set_hash,
        "candidate_ids": _csv_ids(candidate_ids),
        "model_name": model_name,
        "model_version": model_version,
    }


def _json_array(
    value: str | list[dict[str, Any]] | None,
    field_name: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        parsed = value
    else:
        if not value.strip():
            return []
        parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} 必须是 JSON 数组")
    if not all(isinstance(item, dict) for item in parsed):
        raise ValueError(f"{field_name} 每一项都必须是对象")
    return parsed


def _parse_highlights(value: str | list[dict[str, Any]] | None) -> list[SubjectHighlight]:
    return [SubjectHighlight(**item) for item in _json_array(value, "highlights")]


def _parse_sections(value: str | list[dict[str, Any]]) -> list[SubjectReviewSection]:
    return [SubjectReviewSection(**item) for item in _json_array(value, "sections")]


def _parse_trend(value: str | dict[str, Any] | None) -> SubjectReviewTrend | None:
    if value is None:
        return None
    if isinstance(value, dict):
        parsed = value
    else:
        if not value.strip():
            return None
        parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("trend 必须是 JSON 对象")
    return SubjectReviewTrend(**parsed)


def _required_datetime(value: str | None, field_name: str) -> datetime:
    parsed = parse_datetime_optional(value)
    if parsed is None:
        raise ValueError(f"{field_name} 不能为空")
    return parsed


def _candidate_ids_from_matches(matches: list[Any]) -> list[str]:
    return sorted({match.tweet_id for match in matches if match.tweet_id})


def _subject_repo() -> Any:
    repo_factory = cast(Callable[[], Any], get_subject_repo)
    return repo_factory()


def _conflict_response(error: ReviewConflictError) -> str:
    covered_until = error.covered_until.isoformat() if error.covered_until else None
    return json.dumps(
        {
            "success": False,
            "error_type": "conflict",
            "error": str(error),
            "latest_version": error.latest_version,
            "covered_until": covered_until,
        },
        ensure_ascii=False,
    )


def register(mcp: FastMCP) -> None:
    """注册 Subject 只读与增量拉取工具。"""

    @mcp.tool()
    async def list_subjects(status: str | None = None) -> str:
        """列出议题，支持按 active/paused 状态过滤。"""
        try:
            if status not in (None, "active", "paused"):
                return error_response("status 只能是 active 或 paused", "validation")
            repo = get_subject_repo()
            subjects = await repo.list_subjects(status)
            items = []
            for subject in subjects:
                items.append(
                    {
                        "subject_id": subject.subject_id,
                        "name": subject.name,
                        "status": subject.status.value,
                        "keywords": subject.keywords,
                        "last_updated_at": subject.last_updated_at,
                        "match_count": await repo.count_matches(subject.subject_id),
                        "created_at": subject.created_at,
                    }
                )
            return success_response({"subjects": items, "count": len(items)})
        except Exception as e:  # noqa: BLE001
            logger.error("list_subjects 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_subject_feed(
        subject_id: str,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
        time_axis: str = "ingest",
    ) -> str:
        """获取某议题下命中推文流；publish 按 created_at 锁候选并与写入校验同口径。"""
        try:
            repo = get_subject_repo()
            if await repo.get_subject(subject_id) is None:
                return error_response(
                    "议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found"
                )
            data = await repo.get_subject_feed(
                subject_id,
                since=parse_datetime_optional(since),
                until=parse_datetime_optional(until),
                limit=limit,
                time_axis=time_axis,
            )
            return success_response(data)
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_feed 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_subject_candidate_set(
        subject_id: str,
        time_axis: str,
        interval_start: str | None = None,
        interval_end: str | None = None,
    ) -> str:
        """取某议题在指定口径下的权威候选 tweet_id 全集 + candidate_set_hash 指纹。

        用于写 provenance 前与服务端写入校验器对齐。

        time_axis:
          - publish: 按推文发布时间(created_at)圈窗；需 interval_start/interval_end
          - ingest : 按入库时间(matched_at)圈窗，since>= / until<；需 interval_start/interval_end
          - review : 全量，忽略区间
        不支持 time_axis=match；match 候选=技能自持 tweet_ids，技能自算 hash。

        圈候选请用本工具；勿用 get_subject_feed 的 id 算 candidate_set_hash。
        feed 有分页(<=500)与边界口径差异，会导致 provenance 写入校验拒收。

        返回: candidate_ids(全集不分页), candidate_set_hash, count, time_axis,
        interval_start, interval_end, skipped_no_publish_time。
        """
        try:
            repo = _subject_repo()
            if await repo.get_subject(subject_id) is None:
                return error_response(
                    "议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found"
                )
            if time_axis not in {"publish", "ingest", "review"}:
                return error_response("time_axis 只能是 publish / ingest / review", "validation")

            skipped_no_publish_time = 0
            start_dt: datetime | None = None
            end_dt: datetime | None = None
            if time_axis in {"publish", "ingest"}:
                if interval_start is None or interval_end is None:
                    return error_response(
                        "该口径需提供 interval_start 与 interval_end", "validation"
                    )
                start_dt = parse_datetime_optional(interval_start)
                end_dt = parse_datetime_optional(interval_end)
                if start_dt is None or end_dt is None:
                    return error_response(
                        "该口径需提供 interval_start 与 interval_end", "validation"
                    )
                if start_dt > end_dt:
                    return error_response(
                        "区间倒置：interval_start 必须早于 interval_end", "validation"
                    )
                if time_axis == "publish":
                    matches = await repo._publish_window_matches(
                        subject_id,
                        start=start_dt,
                        end=end_dt,
                    )
                    skipped_no_publish_time = len(
                        getattr(matches, "skipped_no_publish_time_ids", [])
                    )
                else:
                    matches = await repo.list_matches(
                        subject_id,
                        since=start_dt,
                        until=end_dt,
                    )
            else:
                matches = await repo.list_matches(subject_id)

            candidate_ids = _candidate_ids_from_matches(matches)
            data = {
                "candidate_ids": candidate_ids,
                "candidate_set_hash": build_candidate_set_hash(candidate_ids),
                "count": len(candidate_ids),
                "time_axis": time_axis,
                "interval_start": start_dt.isoformat() if start_dt is not None else None,
                "interval_end": end_dt.isoformat() if end_dt is not None else None,
                "skipped_no_publish_time": skipped_no_publish_time,
            }
            audit_log(
                "get_subject_candidate_set",
                "read",
                params={"subject_id": subject_id, "time_axis": time_axis},
            )
            return success_response(data)
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_candidate_set 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def put_subject_matches(
        subject_id: str,
        tweet_ids: str,
        relevance: float | None = None,
        reason: str | None = None,
        playbook_id: str | None = None,
        playbook_version: str | None = None,
        prompt_hash: str | None = None,
        candidate_set_hash: str | None = None,
        candidate_ids: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> str:
        """写回外部技能分类命中，成功后关闭待分类；溯源写成时返回 provenance_key。"""
        denied = require_scope("subjects:write")
        if denied is not None:
            audit_log(
                "put_subject_matches",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error="permission",
            )
            return denied
        try:
            data = await SubjectClassifier(get_subject_repo()).write_matches(
                subject_id=subject_id,
                tweet_ids=_csv_ids(tweet_ids),
                relevance=relevance,
                reason=reason,
                provenance=_collect_provenance(
                    playbook_id,
                    playbook_version,
                    prompt_hash,
                    candidate_set_hash,
                    candidate_ids,
                    model_name,
                    model_version,
                ),
            )
            audit_log("put_subject_matches", "write", params={"subject_id": subject_id})
            return success_response(data)
        except LookupError as e:
            audit_log(
                "put_subject_matches",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except ValueError as e:
            audit_log(
                "put_subject_matches",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "put_subject_matches",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("put_subject_matches 失败: %s", e, exc_info=True)
            return error_response(f"写入失败: {e}")

    @mcp.tool()
    async def put_subject_digest(
        subject_id: str,
        interval_start: str,
        interval_end: str,
        time_axis: str = "ingest",
        digest_text: str = "",
        highlights: str | list[dict[str, Any]] | None = None,
        cited: str | None = None,
        playbook_id: str | None = None,
        playbook_version: str | None = None,
        prompt_hash: str | None = None,
        candidate_set_hash: str | None = None,
        candidate_ids: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> str:
        """写回区间滚动新闻；publish 按 created_at 圈候选并校验 cited/highlights 引用。

        highlights 可传 JSON 字符串或对象数组；publish 成功时返回 skipped_no_publish_time。
        溯源写成时返回 provenance_key，可填入 eval 的 target_provenance_ref。
        """
        denied = require_scope("subjects:write")
        if denied is not None:
            audit_log(
                "put_subject_digest",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error="permission",
            )
            return denied
        try:
            data = await SubjectDigestService(get_subject_repo()).write_digest(
                subject_id=subject_id,
                interval_start=_required_datetime(interval_start, "interval_start"),
                interval_end=_required_datetime(interval_end, "interval_end"),
                time_axis=time_axis,
                digest_text=digest_text,
                highlights=_parse_highlights(highlights),
                cited_tweet_ids=_csv_ids(cited),
                provenance=_collect_provenance(
                    playbook_id,
                    playbook_version,
                    prompt_hash,
                    candidate_set_hash,
                    candidate_ids,
                    model_name,
                    model_version,
                ),
            )
            audit_log("put_subject_digest", "write", params={"subject_id": subject_id})
            return success_response(data)
        except LookupError as e:
            audit_log(
                "put_subject_digest",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            audit_log(
                "put_subject_digest",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "put_subject_digest",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("put_subject_digest 失败: %s", e, exc_info=True)
            return error_response(f"写入失败: {e}")

    @mcp.tool()
    async def put_subject_review(
        subject_id: str,
        prev_version: int,
        sections: str | list[dict[str, Any]],
        covered_until: str,
        trend: str | dict[str, Any] | None = None,
        cited: str | None = None,
        playbook_id: str | None = None,
        playbook_version: str | None = None,
        prompt_hash: str | None = None,
        candidate_set_hash: str | None = None,
        candidate_ids: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> str:
        """写回累积综述；sections 收 JSON 字符串或数组，trend 收字符串或对象。

        溯源写成时返回 provenance_key，可填入 eval 的 target_provenance_ref。
        """
        denied = require_scope("subjects:write")
        if denied is not None:
            audit_log(
                "put_subject_review",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error="permission",
            )
            return denied
        try:
            data = await SubjectReviewService(get_subject_repo()).write_review(
                subject_id=subject_id,
                prev_version=prev_version,
                sections=_parse_sections(sections),
                covered_until=_required_datetime(covered_until, "covered_until"),
                trend=_parse_trend(trend),
                cited_tweet_ids=_csv_ids(cited),
                provenance=_collect_provenance(
                    playbook_id,
                    playbook_version,
                    prompt_hash,
                    candidate_set_hash,
                    candidate_ids,
                    model_name,
                    model_version,
                ),
            )
            audit_log("put_subject_review", "write", params={"subject_id": subject_id})
            return success_response(data)
        except ReviewConflictError as e:
            audit_log(
                "put_subject_review",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return _conflict_response(e)
        except LookupError as e:
            audit_log(
                "put_subject_review",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            audit_log(
                "put_subject_review",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "put_subject_review",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("put_subject_review 失败: %s", e, exc_info=True)
            return error_response(f"写入失败: {e}")

    @mcp.tool()
    async def get_pending_jobs(subject_id: str | None = None) -> str:
        """列出待分类/待综述议题。"""
        try:
            repo = get_subject_repo()
            items = await repo.list_pending(subject_id)
            audit_log("get_pending_jobs", "read", params={"subject_id": subject_id})
            return success_response({"items": items, "count": len(items)})
        except Exception as e:  # noqa: BLE001
            audit_log(
                "get_pending_jobs",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("get_pending_jobs 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_subject_digest(
        subject_id: str,
        start: str | None = None,
        end: str | None = None,
    ) -> str:
        """按区间获取议题滚动新闻；都不传返回最新一条。"""
        try:
            repo = get_subject_repo()
            if await repo.get_subject(subject_id) is None:
                return error_response(
                    "议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found"
                )
            start_dt = parse_datetime_optional(start)
            end_dt = parse_datetime_optional(end)
            digest = await repo.get_digest(subject_id, start=start_dt, end=end_dt)
            if digest is None:
                return success_response(
                    {
                        "subject_id": subject_id,
                        "interval_start": start,
                        "interval_end": end,
                        "time_axis": None,
                        "tweet_count": 0,
                        "digest_text": "",
                        "highlights": [],
                        "cited_tweet_ids": [],
                        "generated_at": None,
                    }
                )
            return success_response(digest.model_dump(mode="json", exclude={"generated_by"}))
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_digest 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_subject_review(subject_id: str) -> str:
        """读议题当前活综述（L2 全量累积全貌）。从未生成过返回 `version=0` 空壳（不报错），此时请调 `refresh_subject_review` 触发生成。想感知综述是否更新：周期性调本工具，比对返回的 `version` / `updated_at`——本版本不通过 `get_subject_updates` 推送 review 事件。"""
        try:
            payload = await SubjectReviewService(get_subject_repo()).get_review_payload(subject_id)
            if payload is None:
                return error_response(
                    "议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found"
                )
            return success_response(payload)
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_review 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def refresh_subject_review(subject_id: str | None = None) -> str:
        """单议题刷新改为挂待综述；全量入口保持占位。"""
        try:
            audit_log(
                "refresh_subject_review",
                "refresh",
                params={"subject_id": subject_id},
            )
            if subject_id is None:
                return success_response(
                    {
                        "migrated": True,
                        "pending": False,
                        "message": REVIEW_MIGRATED_MESSAGE,
                    }
                )
            repo = get_subject_repo()
            if await repo.get_subject(subject_id) is None:
                return error_response(
                    "议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found"
                )
            await repo.set_pending(subject_id, review=True)
            return success_response(
                {
                    "pending": True,
                    "job": "review",
                    "subject_id": subject_id,
                    "message": REVIEW_PENDING_MESSAGE,
                }
            )
        except Exception as e:  # noqa: BLE001
            audit_log(
                "refresh_subject_review",
                "refresh",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("refresh_subject_review 失败: %s", e, exc_info=True)
            return error_response(f"刷新失败: {e}")

    @mcp.tool()
    async def get_subject_updates(
        since_cursor: str | None = None,
        limit: int = 200,
    ) -> str:
        """增量拉取所有 active 议题的更新（跨议题 delta）。游标机制：`since_cursor` 是 **ISO 8601 时间戳字符串**（如 `2026-06-27T14:00:00Z`），表示"只要这个时刻之后的更新"。本工具**服务端无状态**——游标由调用方（Agent）自己持有。每次返回体含 `next_cursor`，**下次调用把它原样传回 `since_cursor` 即可续拉下一批**，无需自己拼时间。首次调用 `since_cursor` 留空 → 返回近期窗口 + 首个 `next_cursor`。delta 为空 → 返回空列表 + 原 `next_cursor`（可安全重复轮询）。"""
        try:
            data = await get_subject_repo().get_updates(
                since_cursor=since_cursor,
                limit=limit,
            )
            return success_response(data)
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_updates 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_tweets_by_ids(tweet_ids: str) -> str:
        """按内部 tweet_id 批量解析推文原文；缺失 id 进入 missing_ids。"""
        try:
            ids = [item.strip() for item in tweet_ids.split(",") if item.strip()]
            if not ids:
                return error_response("tweet_ids 不能为空", "validation")
            items, missing = await get_subject_repo().get_tweets_by_ids(ids)
            return success_response(
                {
                    "items": items,
                    "found_count": len(items),
                    "missing_ids": missing,
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.error("get_tweets_by_ids 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def put_subject_feedback(
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
    ) -> str:
        """写入议题派生物反馈裁决，append-only 落 subjects/<sid>/feedback/YYYY-MM.jsonl。"""
        denied = require_scope("subjects:write")
        if denied is not None:
            audit_log(
                "put_subject_feedback",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error="permission",
            )
            return denied
        try:
            feedback = await SubjectFeedbackService(get_subject_repo()).put_feedback(
                subject_id=subject_id,
                target_type=target_type,
                target_id=target_id,
                verdict=verdict,
                authority=authority,
                who=who,
                provenance_key=provenance_key,
                corrected_value=corrected_value,
                note=note,
                supersedes=supersedes,
            )
            audit_log(
                "put_subject_feedback",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
            )
            return success_response(feedback.model_dump(mode="json"))
        except LookupError as e:
            audit_log(
                "put_subject_feedback",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            audit_log(
                "put_subject_feedback",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "put_subject_feedback",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("put_subject_feedback 失败: %s", e, exc_info=True)
            return error_response("写入失败: feedback 裁决未落盘，请稍后重试", "internal")

    @mcp.tool()
    async def get_subject_feedback(
        subject_id: str,
        target_id: str | None = None,
        target_type: str | None = None,
    ) -> str:
        """读取议题当前有效反馈裁决，可按 target_id 或 target_type 过滤。"""
        try:
            feedbacks, cycle_targets = await SubjectFeedbackService(
                get_subject_repo()
            ).get_current_feedbacks(
                subject_id=subject_id,
                target_id=target_id,
                target_type=target_type,
            )
            for cycle_target in cycle_targets:
                audit_log(
                    "get_subject_feedback",
                    "read",
                    params={"subject_id": subject_id, "target_id": cycle_target},
                    result="warning",
                    error="superseded_cycle_detected",
                )
            audit_log(
                "get_subject_feedback",
                "read",
                params={"subject_id": subject_id, "target_type": target_type},
            )
            return success_response(
                {
                    "subject_id": subject_id,
                    "count": len(feedbacks),
                    "feedbacks": feedbacks,
                }
            )
        except LookupError as e:
            audit_log(
                "get_subject_feedback",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError) as e:
            audit_log(
                "get_subject_feedback",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "get_subject_feedback",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("get_subject_feedback 失败: %s", e, exc_info=True)
            return error_response("查询失败: feedback 裁决读取失败", "internal")

    @mcp.tool()
    async def put_subject_eval(
        subject_id: str,
        target_id: str,
        tier: str,
        scores: str | None = None,
        target_provenance_ref: str | None = None,
        rubric_version: str | None = None,
        judge_model: str | None = None,
        judge_human_kappa: float | None = None,
        note: str | None = None,
        hard_fail: bool | None = None,
        failed_checks: str | None = None,
        warnings: str | None = None,
    ) -> str:
        """写 judge/human eval 记录；hygiene 档请调 run_subject_hygiene_check。

        target_id 示例：match::<sid>::<tweet_id> /
        digest::<sid>::<interval_start>::<time_axis> / review::<sid>::<version>。
        eval 纯追加，评错再评一条；读侧按 when 取最新。
        """
        denied = require_scope("subjects:write")
        if denied is not None:
            audit_log(
                "put_subject_eval",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error="permission",
            )
            return denied
        try:
            if hard_fail is not None or failed_checks is not None or warnings is not None:
                raise ValueError("hard_fail / failed_checks / warnings 只能由卫生计算工具产生")
            eval_record = await SubjectEvalService(get_subject_repo()).put_eval(
                subject_id=subject_id,
                target_id=target_id,
                tier=tier,
                scores=scores,
                target_provenance_ref=target_provenance_ref,
                rubric_version=rubric_version,
                judge_model=judge_model,
                judge_human_kappa=judge_human_kappa,
                note=note,
            )
            audit_log(
                "put_subject_eval",
                "write",
                params={"subject_id": subject_id, "tier": tier},
            )
            return success_response(eval_record.model_dump(mode="json"))
        except LookupError as e:
            audit_log(
                "put_subject_eval",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            audit_log(
                "put_subject_eval",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except OSError as e:
            audit_log(
                "put_subject_eval",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("put_subject_eval 失败: %s", e, exc_info=True)
            return error_response("写入失败: eval 记录未落盘，请稍后重试", "internal")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "put_subject_eval",
                "write",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("put_subject_eval 失败: %s", e, exc_info=True)
            return error_response("写入失败: eval 记录未落盘，请稍后重试", "internal")

    @mcp.tool()
    async def get_subject_eval(
        subject_id: str,
        target_id: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """读取 eval 记录，可按 target_id/tier/[since,until) 过滤；不分页。"""
        try:
            data = await SubjectEvalService(get_subject_repo()).get_evals(
                subject_id=subject_id,
                target_id=target_id,
                tier=tier,
                since=since,
                until=until,
            )
            audit_log(
                "get_subject_eval",
                "read",
                params={"subject_id": subject_id, "tier": tier},
            )
            return success_response(data)
        except LookupError as e:
            audit_log(
                "get_subject_eval",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError) as e:
            audit_log(
                "get_subject_eval",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "get_subject_eval",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("get_subject_eval 失败: %s", e, exc_info=True)
            return error_response("查询失败: eval 记录读取失败", "internal")

    @mcp.tool()
    async def run_subject_hygiene_check(
        subject_id: str,
        target_type: str,
        interval_start: str | None = None,
        time_axis: str | None = None,
        generated_at: str | None = None,
        version: int | None = None,
    ) -> str:
        """对 digest/review 跑确定性卫生体检并自动落 tier=hygiene eval 记录。"""
        denied = require_scope("subjects:write")
        if denied is not None:
            audit_log(
                "run_subject_hygiene_check",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
                result="failure",
                error="permission",
            )
            return denied
        try:
            data = await SubjectHygieneService(get_subject_repo()).run_check(
                subject_id=subject_id,
                target_type=target_type,
                interval_start=interval_start,
                time_axis=time_axis,
                generated_at=generated_at,
                version=version,
            )
            audit_log(
                "run_subject_hygiene_check",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
            )
            return success_response(data)
        except LookupError as e:
            audit_log(
                "run_subject_hygiene_check",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError) as e:
            audit_log(
                "run_subject_hygiene_check",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except OSError as e:
            audit_log(
                "run_subject_hygiene_check",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
                result="failure",
                error=str(e),
            )
            logger.error("run_subject_hygiene_check 失败: %s", e, exc_info=True)
            return error_response("写入失败: eval 记录未落盘，请稍后重试", "internal")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "run_subject_hygiene_check",
                "write",
                params={"subject_id": subject_id, "target_type": target_type},
                result="failure",
                error=str(e),
            )
            logger.error("run_subject_hygiene_check 失败: %s", e, exc_info=True)
            return error_response("写入失败: eval 记录未落盘，请稍后重试", "internal")

    @mcp.tool()
    async def get_subject_correction_rate(subject_id: str, window_days: int) -> str:
        """读取近 N 天 rolling 窗口内人工更正率；纯读不落盘。"""
        try:
            data, cycle_targets = await SubjectEvalService(get_subject_repo()).get_correction_rate(
                subject_id=subject_id,
                window_days=window_days,
            )
            for cycle_target in cycle_targets:
                audit_log(
                    "get_subject_correction_rate",
                    "read",
                    params={"subject_id": subject_id, "target_id": cycle_target},
                    result="warning",
                    error="superseded_cycle_detected",
                )
            audit_log(
                "get_subject_correction_rate",
                "read",
                params={"subject_id": subject_id, "window_days": window_days},
            )
            return success_response(data)
        except LookupError as e:
            audit_log(
                "get_subject_correction_rate",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "not_found")
        except (ValueError, TypeError) as e:
            audit_log(
                "get_subject_correction_rate",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            return error_response(str(e), "validation")
        except Exception as e:  # noqa: BLE001
            audit_log(
                "get_subject_correction_rate",
                "read",
                params={"subject_id": subject_id},
                result="failure",
                error=str(e),
            )
            logger.error("get_subject_correction_rate 失败: %s", e, exc_info=True)
            return error_response("查询失败: 人工更正率读取失败", "internal")
