"""MCP 系统状态工具。

提供 get_system_status 工具，聚合返回系统各维度关键指标。
"""

import asyncio
import logging

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import error_response, success_response

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册系统状态 MCP 工具。"""

    @mcp.tool()
    async def get_system_status() -> str:
        """获取系统全局状态概览。

        返回推文数、关注列表、摘要统计、系统信息等关键指标。
        """
        try:
            from src.data_layer.provider import get_status_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()

            async def _tweet_stats():
                async with session_maker() as s:
                    stats = await get_status_repo(s).get_tweet_stats()
                    return {
                        "total": stats.total,
                        "latest_tweet_at": stats.latest_tweet_at,
                        "today_count": stats.today_count,
                    }

            async def _follow_stats():
                async with session_maker() as s:
                    stats = await get_status_repo(s).get_follow_stats()
                    return {
                        "total": stats.total,
                        "active": stats.active,
                        "inactive": stats.inactive,
                    }

            async def _summary_stats():
                async with session_maker() as s:
                    stats = await get_status_repo(s).get_summary_stats()
                    return {
                        "total": stats.total,
                        "pending_tweets": stats.pending_tweets,
                    }

            tweets, follows, summaries = await asyncio.gather(
                _tweet_stats(),
                _follow_stats(),
                _summary_stats(),
            )

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

            return success_response(
                {
                    "tweets": tweets,
                    "follows": follows,
                    "summaries": summaries,
                    "external_dependencies": external_deps,
                    "system": {
                        "database_size_mb": database_size_mb,
                        "mcp_mode": True,
                    },
                }
            )
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
                return success_response(
                    {
                        "logs": [],
                        "count": 0,
                        "note": "file 模式审计仅文件日志,无 DB 查询",
                    }
                )

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

                return success_response(
                    {
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
                    }
                )
        except Exception as e:
            logger.error("get_audit_log 失败: %s", e, exc_info=True)
            return error_response(f"查询审计日志失败: {e}")
