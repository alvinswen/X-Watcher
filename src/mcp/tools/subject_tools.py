"""MCP Subject 议题工具。"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from src.data_layer.provider import get_subject_repo
from src.mcp.helpers import error_response, parse_datetime_optional, success_response
from src.mcp.security import audit_log
from src.subjects.services.review_service import SubjectReviewService

logger = logging.getLogger(__name__)


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
                items.append({
                    "subject_id": subject.subject_id,
                    "name": subject.name,
                    "status": subject.status.value,
                    "keywords": subject.keywords,
                    "last_updated_at": subject.last_updated_at,
                    "match_count": await repo.count_matches(subject.subject_id),
                    "created_at": subject.created_at,
                })
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
    ) -> str:
        """获取某议题下命中推文流（内联推文+摘要，游标分页）。"""
        try:
            repo = get_subject_repo()
            if await repo.get_subject(subject_id) is None:
                return error_response("议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found")
            data = await repo.get_subject_feed(
                subject_id,
                since=parse_datetime_optional(since),
                until=parse_datetime_optional(until),
                limit=limit,
            )
            return success_response(data)
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_feed 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_subject_digest(subject_id: str, hour: str | None = None) -> str:
        """获取某议题某 UTC 小时桶滚动新闻；hour 留空返回最新桶。"""
        try:
            repo = get_subject_repo()
            if await repo.get_subject(subject_id) is None:
                return error_response("议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found")
            digest = await repo.get_digest(subject_id, hour)
            if digest is None:
                return success_response({
                    "hour": hour,
                    "tweet_count": 0,
                    "digest_text": "",
                    "highlights": [],
                    "cited_tweet_ids": [],
                    "generated_at": None,
                })
            return success_response(digest.model_dump(mode="json", exclude={"generated_by"}))
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_digest 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_subject_review(subject_id: str) -> str:
        """读议题当前活综述（L2 全量累积全貌）。从未生成过返回 `version=0` 空壳（不报错），此时请调 `refresh_subject_review` 触发生成。想感知综述是否更新：周期性调本工具，比对返回的 `version` / `updated_at`——本版本不通过 `get_subject_updates` 推送 review 事件。"""
        try:
            payload = await SubjectReviewService(get_subject_repo()).get_review_payload(subject_id)
            if payload is None:
                return error_response("议题不存在，请先调用 list_subjects 获取有效 subject_id", "not_found")
            return success_response(payload)
        except Exception as e:  # noqa: BLE001
            logger.error("get_subject_review 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def refresh_subject_review(subject_id: str | None = None) -> str:
        """返回综述生成迁移占位；服务端生成链已移除。"""
        try:
            audit_log(
                "refresh_subject_review",
                "refresh",
                params={"subject_id": subject_id},
            )
            return success_response({
                "migrated": True,
                "pending": False,
                "message": "综述生成已迁移至外部技能，刷新功能将在后续版本改为挂待办",
            })
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
            return success_response({
                "items": items,
                "found_count": len(items),
                "missing_ids": missing,
            })
        except Exception as e:  # noqa: BLE001
            logger.error("get_tweets_by_ids 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")
