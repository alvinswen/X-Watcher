"""MCP Subject 议题工具。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.data_layer.provider import get_subject_repo
from src.mcp.auth import require_scope
from src.mcp.helpers import error_response, parse_datetime_optional, success_response
from src.mcp.security import audit_log
from src.subjects.models import SubjectHighlight, SubjectReviewSection, SubjectReviewTrend
from src.subjects.services.classifier import SubjectClassifier
from src.subjects.services.digest_service import SubjectDigestService
from src.subjects.services.review_service import ReviewConflictError, SubjectReviewService

logger = logging.getLogger(__name__)
REVIEW_PENDING_MESSAGE = "综述刷新已加入待综述队列，外部技能将异步处理"
REVIEW_MIGRATED_MESSAGE = "综述生成已迁移至外部技能，全量刷新入口暂不批量挂待办"


def _csv_ids(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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
    async def put_subject_matches(
        subject_id: str,
        tweet_ids: str,
        relevance: float | None = None,
        reason: str | None = None,
    ) -> str:
        """写回外部技能分类命中，成功后关闭待分类。"""
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
    ) -> str:
        """写回区间滚动新闻；publish 按 created_at 圈候选并校验 cited/highlights 引用。

        highlights 可传 JSON 字符串或对象数组；publish 成功时返回 skipped_no_publish_time。
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
    ) -> str:
        """写回累积综述；sections 收 JSON 字符串或数组，trend 收字符串或对象。"""
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
