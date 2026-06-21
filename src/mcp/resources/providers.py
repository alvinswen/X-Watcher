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
            from sqlalchemy import func, select

            from src.database.async_session import get_async_session_maker
            from src.database.models import ScraperFollow
            from src.scraper.infrastructure.models import TweetOrm
            from src.summarization.infrastructure.models import SummaryOrm
            from src.topic.infrastructure.models import TopicOrm

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                tweet_count = (
                    await session.execute(
                        select(func.count()).select_from(TweetOrm)
                    )
                ).scalar() or 0

                follow_count = (
                    await session.execute(
                        select(func.count()).select_from(ScraperFollow)
                    )
                ).scalar() or 0

                summary_count = (
                    await session.execute(
                        select(func.count()).select_from(SummaryOrm)
                    )
                ).scalar() or 0

                topic_count = (
                    await session.execute(
                        select(func.count()).select_from(TopicOrm)
                    )
                ).scalar() or 0

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
            from sqlalchemy import select

            from src.database.async_session import get_async_session_maker
            from src.database.models import ScraperFollow

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(
                        ScraperFollow.username,
                        ScraperFollow.reason,
                        ScraperFollow.is_active,
                        ScraperFollow.added_at,
                        ScraperFollow.brief_intro,
                    ).order_by(ScraperFollow.username)
                )
                rows = result.fetchall()

                follows = [
                    {
                        "username": r.username,
                        "reason": r.reason,
                        "is_active": r.is_active,
                        "added_at": r.added_at,
                        "brief_intro": r.brief_intro,
                    }
                    for r in rows
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
            from sqlalchemy import func, select

            from src.database.async_session import get_async_session_maker
            from src.topic.infrastructure.models import TopicAccountOrm, TopicOrm

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(
                        TopicOrm.id,
                        TopicOrm.name,
                        TopicOrm.description,
                        TopicOrm.created_at,
                    ).order_by(TopicOrm.name)
                )
                topics_rows = result.fetchall()

                topics = []
                for t in topics_rows:
                    # 查询每个主题的账号数
                    acc_count_r = await session.execute(
                        select(func.count())
                        .select_from(TopicAccountOrm)
                        .where(TopicAccountOrm.topic_id == t.id)
                    )
                    acc_count = acc_count_r.scalar() or 0

                    topics.append({
                        "id": t.id,
                        "name": t.name,
                        "description": t.description,
                        "created_at": t.created_at,
                        "account_count": acc_count,
                    })

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
