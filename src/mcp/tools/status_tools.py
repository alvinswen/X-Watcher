"""MCP 系统状态工具。

提供 get_system_status 工具，聚合返回系统各维度关键指标。
"""

import asyncio
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import error_response, success_response

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册系统状态 MCP 工具。"""

    @mcp.tool()
    async def get_system_status() -> str:
        """获取系统全局状态概览。

        返回推文数、关注列表、摘要统计、主题统计、调度器状态、系统信息等关键指标。
        """
        try:
            from sqlalchemy import func, select

            from src.database.async_session import get_async_session_maker
            from src.database.models import ScraperFollow
            from src.scraper.infrastructure.models import TweetOrm
            from src.summarization.infrastructure.models import SummaryOrm
            from src.topic.infrastructure.models import TopicOrm, TopicSummaryTaskOrm

            session_maker = get_async_session_maker()

            async def _tweet_stats():
                async with session_maker() as s:
                    total_r = await s.execute(
                        select(func.count()).select_from(TweetOrm)
                    )
                    total = total_r.scalar() or 0

                    latest_r = await s.execute(
                        select(func.max(TweetOrm.created_at))
                    )
                    latest = latest_r.scalar()

                    today_start = datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    today_r = await s.execute(
                        select(func.count())
                        .select_from(TweetOrm)
                        .where(TweetOrm.created_at >= today_start)
                    )
                    today = today_r.scalar() or 0

                    return {
                        "total": total,
                        "latest_tweet_at": latest,
                        "today_count": today,
                    }

            async def _follow_stats():
                async with session_maker() as s:
                    total_r = await s.execute(
                        select(func.count()).select_from(ScraperFollow)
                    )
                    total = total_r.scalar() or 0

                    active_r = await s.execute(
                        select(func.count())
                        .select_from(ScraperFollow)
                        .where(ScraperFollow.is_active == True)  # noqa: E712
                    )
                    active = active_r.scalar() or 0

                    return {
                        "total": total,
                        "active": active,
                        "inactive": total - active,
                    }

            async def _summary_stats():
                async with session_maker() as s:
                    total_r = await s.execute(
                        select(func.count()).select_from(SummaryOrm)
                    )
                    total = total_r.scalar() or 0

                    pending_r = await s.execute(
                        select(func.count())
                        .select_from(TweetOrm)
                        .outerjoin(
                            SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id
                        )
                        .where(SummaryOrm.summary_id == None)  # noqa: E711
                    )
                    pending = pending_r.scalar() or 0

                    return {"total": total, "pending_tweets": pending}

            async def _topic_stats():
                async with session_maker() as s:
                    total_r = await s.execute(
                        select(func.count()).select_from(TopicOrm)
                    )
                    total = total_r.scalar() or 0

                    latest_r = await s.execute(
                        select(
                            TopicSummaryTaskOrm.completed_at,
                            TopicSummaryTaskOrm.status,
                        )
                        .order_by(TopicSummaryTaskOrm.created_at.desc())
                        .limit(1)
                    )
                    latest = latest_r.first()

                    return {
                        "total": total,
                        "latest_summary_at": (
                            latest.completed_at if latest else None
                        ),
                        "latest_summary_status": (
                            latest.status if latest else None
                        ),
                    }

            tweets, follows, summaries, topics = await asyncio.gather(
                _tweet_stats(),
                _follow_stats(),
                _summary_stats(),
                _topic_stats(),
            )

            # 调度器状态（MCP 进程不启动调度器，查询 DB 配置）
            scheduler_info = {"status": "not_running_in_mcp"}
            try:
                from src.data_layer.provider import get_schedule_repo

                async with session_maker() as s:
                    repo = get_schedule_repo(s)
                    config = await repo.get_schedule_config()
                    if config:
                        scheduler_info = {
                            "status": "enabled" if config.is_enabled else "disabled",
                            "interval_seconds": config.interval_seconds,
                            "next_run_time": config.next_run_time,
                            "note": "调度器在 FastAPI 服务中运行，MCP 仅显示配置",
                        }
            except Exception:
                pass

            # 系统信息
            from src.database.dialect import get_database_size_mb

            database_size_mb = get_database_size_mb()

            # 外部依赖健康状态
            external_deps = {}
            try:
                from src.scraper.client import get_twitter_circuit_breaker

                cb = get_twitter_circuit_breaker()
                external_deps["twitter_api"] = cb.get_status()
            except Exception:
                external_deps["twitter_api"] = {"state": "unknown"}

            return success_response({
                "tweets": tweets,
                "follows": follows,
                "summaries": summaries,
                "topics": topics,
                "scheduler": scheduler_info,
                "external_dependencies": external_deps,
                "system": {
                    "database_size_mb": database_size_mb,
                    "mcp_mode": True,
                },
            })
        except Exception as e:
            logger.error("get_system_status 失败: %s", e, exc_info=True)
            return error_response(f"获取系统状态失败: {e}")

    @mcp.tool()
    async def get_audit_log(
        limit: int = 50,
        tool: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """查询审计日志（只读）。

        Args:
            limit: 返回条数上限，默认 50，最大 200
            tool: 按工具名过滤（如 "manage_follows"、"trigger_scrape"）
            action: 按操作类型过滤（如 "add"、"delete"、"scrape"）
            since: 起始时间（含），ISO 8601 格式
            until: 截止时间（不含），ISO 8601 格式
        """
        try:
            from src.data_layer.provider import is_file_mode

            if is_file_mode():
                # file 模式:审计仅文件日志,无 DB 持久化可查 → 返空结构(沿现有形态)
                return success_response({
                    "logs": [],
                    "count": 0,
                    "note": "file 模式审计仅文件日志,无 DB 查询",
                })

            import json

            from sqlalchemy import select

            from src.database.async_session import get_async_session_maker
            from src.database.models import AuditLog
            from src.mcp.helpers import parse_datetime_optional

            clamped_limit = min(max(limit, 1), 200)
            since_dt = parse_datetime_optional(since)
            until_dt = parse_datetime_optional(until)

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                query = select(AuditLog).order_by(AuditLog.timestamp.desc())

                if tool:
                    query = query.where(AuditLog.tool == tool)
                if action:
                    query = query.where(AuditLog.action == action)
                if since_dt:
                    query = query.where(AuditLog.timestamp >= since_dt)
                if until_dt:
                    query = query.where(AuditLog.timestamp < until_dt)

                query = query.limit(clamped_limit)
                result = await session.execute(query)
                logs = result.scalars().all()

                return success_response({
                    "logs": [
                        {
                            "id": log.id,
                            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                            "tool": log.tool,
                            "action": log.action,
                            "user": log.user,
                            "params": json.loads(log.params_json) if log.params_json else None,
                            "result": log.result,
                            "error": log.error,
                            "source": log.source,
                        }
                        for log in logs
                    ],
                    "count": len(logs),
                })
        except Exception as e:
            logger.error("get_audit_log 失败: %s", e, exc_info=True)
            return error_response(f"查询审计日志失败: {e}")
