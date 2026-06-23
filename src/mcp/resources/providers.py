"""MCP 动态资源提供者。

提供 4 个动态资源：系统状态、关注列表、监控主题、服务配置。
"""

import json
import logging
from datetime import datetime

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _default_serializer(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def register(mcp: FastMCP) -> None:
    """注册 MCP 动态资源。"""

    @mcp.resource("xwatcher://status")
    async def status_resource() -> str:
        """当前系统健康状态和关键统计。"""
        try:
            from src.data_layer.provider import get_status_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = get_status_repo(session)
                tweet_count = (await repo.get_tweet_stats()).total
                follow_count = (await repo.get_follow_stats()).total
                summary_count = (await repo.get_summary_stats()).total
                topic_count = (await repo.get_topic_stats()).total

            return json.dumps(
                {
                    "tweets": tweet_count,
                    "follows": follow_count,
                    "summaries": summary_count,
                    "topics": topic_count,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.resource("xwatcher://follows")
    async def follows_resource() -> str:
        """正在监控的 X 账号列表。"""
        try:
            from src.data_layer.provider import get_follows_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                # 源无 is_active 过滤=返全部 → include_inactive=True
                all_follows = await get_follows_repo(session).get_all_follows(
                    include_inactive=True
                )

            # 保留源行为:按 username 升序(repo 默认 added_at DESC)
            all_follows = sorted(all_follows, key=lambda f: f.username)
            follows = [
                {
                    "username": f.username,
                    "reason": f.reason,
                    "is_active": f.is_active,
                    "added_at": f.added_at,
                    "brief_intro": f.brief_intro,
                }
                for f in all_follows
            ]

            return json.dumps(
                {"follows": follows, "count": len(follows)},
                ensure_ascii=False,
                default=_default_serializer,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.resource("xwatcher://topics")
    async def topics_resource() -> str:
        """配置的监控主题及账号关联。"""
        try:
            from src.data_layer.provider import get_topic_store
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                # list_all 返 TopicWithCountDomain(内含 account_count),消除 per-topic count 查询
                all_topics = await get_topic_store(session).list_all()

            # 保留源行为:按 name 升序(list_all 默认 created_at DESC)
            all_topics = sorted(all_topics, key=lambda t: t.name)
            topics = [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "created_at": t.created_at,
                    "account_count": t.account_count,
                }
                for t in all_topics
            ]

            return json.dumps(
                {"topics": topics, "count": len(topics)},
                ensure_ascii=False,
                default=_default_serializer,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.resource("xwatcher://config")
    async def config_resource() -> str:
        """当前抓取和调度配置。"""
        try:
            from src.config import get_settings

            settings = get_settings()

            # 从 DB 查询调度配置
            schedule_config = None
            try:
                from src.database.async_session import get_async_session_maker
                from src.data_layer.provider import get_schedule_repo

                session_maker = get_async_session_maker()
                async with session_maker() as session:
                    repo = get_schedule_repo(session)
                    config = await repo.get_schedule_config()
                    if config:
                        schedule_config = {
                            "interval_seconds": config.interval_seconds,
                            "is_enabled": config.is_enabled,
                            "next_run_time": config.next_run_time,
                        }
            except Exception:
                pass

            return json.dumps(
                {
                    "scraper": {
                        "enabled": settings.scraper_enabled,
                        "default_interval": settings.scraper_interval,
                        "limit": settings.scraper_limit,
                        "early_stop_threshold": settings.scraper_early_stop_threshold,
                        "max_extra_pages": settings.scraper_max_extra_pages,
                    },
                    "schedule": schedule_config,
                    "summarization": {
                        "auto_enabled": settings.auto_summarization_enabled,
                        "batch_size": settings.auto_summarization_batch_size,
                    },
                    "feed": {
                        "max_tweets": settings.feed_max_tweets,
                    },
                },
                ensure_ascii=False,
                default=_default_serializer,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
