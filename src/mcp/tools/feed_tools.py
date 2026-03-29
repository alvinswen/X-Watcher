"""MCP Feed & 搜索工具。

提供 get_feed 和 search_tweets 两个 MCP 工具，映射到 FeedService 和 SearchService。
"""

import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import (
    error_response,
    parse_datetime,
    parse_datetime_optional,
    success_response,
)

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册 Feed 相关 MCP 工具。"""

    @mcp.tool()
    async def get_feed(
        since: str,
        until: str | None = None,
        limit: int = 200,
        include_summary: bool = True,
        author: str | None = None,
        authors: str | None = None,
        keyword: str | None = None,
    ) -> str:
        """获取指定时间范围的增量推文 feed（含摘要），支持按作者/关键词过滤。

        Args:
            since: 起始时间（含），ISO 8601 格式，如 "2026-02-24T00:00:00Z"
            until: 截止时间（不含），ISO 8601 格式。默认为当前时间
            limit: 最大返回条数，默认 200
            include_summary: 是否包含中文摘要和翻译，默认 True
            author: 按单个作者用户名筛选（大小写不敏感）
            authors: 按多个作者筛选，逗号分隔，如 "elonmusk,vaboris"
            keyword: 关键词过滤（搜索推文正文、摘要、翻译）
        """
        try:
            since_dt = parse_datetime(since)
            until_dt = parse_datetime(until) if until else datetime.now(timezone.utc)

            authors_list = (
                [a.strip() for a in authors.split(",") if a.strip()]
                if authors
                else None
            )
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")

        try:
            from src.config import get_settings
            from src.database.async_session import get_async_session_maker
            from src.feed.services.feed_service import FeedService

            # 钳制 limit 到配置上限，防止 OOM
            max_limit = get_settings().feed_max_tweets
            clamped_limit = min(max(limit, 1), max_limit)

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                service = FeedService(session)
                result = await service.get_feed(
                    since=since_dt,
                    until=until_dt,
                    limit=clamped_limit,
                    include_summary=include_summary,
                    author=author,
                    authors=authors_list,
                    keyword=keyword,
                )
                return success_response({
                    "items": result.items,
                    "count": result.count,
                    "total": result.total,
                    "has_more": result.has_more,
                    "since": since_dt.isoformat(),
                    "until": until_dt.isoformat(),
                })
        except Exception as e:
            logger.error("get_feed 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def search_tweets(
        q: str,
        page: int = 1,
        page_size: int = 20,
        include_summary: bool = True,
        author: str | None = None,
        authors: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """多字段关键词搜索推文（正文、摘要、翻译、引用推文）。

        Args:
            q: 搜索关键词，空格分隔多个关键词（AND 逻辑）
            page: 页码（从 1 开始），默认 1
            page_size: 每页条数，默认 20
            include_summary: 是否在搜索范围中包含摘要和翻译字段，默认 True
            author: 按单个作者用户名筛选
            authors: 按多个作者筛选，逗号分隔
            since: 起始时间（含），ISO 8601 格式
            until: 截止时间（不含），ISO 8601 格式
        """
        if not q or not q.strip():
            return error_response("搜索关键词不能为空", "validation")

        try:
            since_dt = parse_datetime_optional(since)
            until_dt = parse_datetime_optional(until)

            authors_list = (
                [a.strip() for a in authors.split(",") if a.strip()]
                if authors
                else None
            )
        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")

        try:
            from src.database.async_session import get_async_session_maker
            from src.search.services.search_service import SearchService

            # 钳制 page_size 到合理范围
            clamped_page_size = min(max(page_size, 1), 100)

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                service = SearchService(session)
                result = await service.search_tweets(
                    q=q.strip(),
                    page=page,
                    page_size=clamped_page_size,
                    include_summary=include_summary,
                    author=author,
                    authors=authors_list,
                    since=since_dt,
                    until=until_dt,
                )
                total_pages = (
                    (result.total + clamped_page_size - 1) // clamped_page_size
                    if result.total > 0
                    else 0
                )
                return success_response({
                    "items": result.items,
                    "total": result.total,
                    "count": len(result.items),
                    "page": page,
                    "page_size": clamped_page_size,
                    "total_pages": total_pages,
                    "q": q.strip(),
                })
        except Exception as e:
            logger.error("search_tweets 失败: %s", e, exc_info=True)
            return error_response(f"搜索失败: {e}")
