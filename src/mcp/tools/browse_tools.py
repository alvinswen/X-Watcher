"""MCP 浏览工具。

提供 get_daily_stats、get_authors_for_date、browse_tweets 三个 MCP 工具，
映射到 browse 读门面（get_browse_repo，file/sqlalchemy 双模）。
"""

import logging

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import error_response, success_response

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册 Browse 相关 MCP 工具。"""

    @mcp.tool()
    async def get_daily_stats(
        year: int,
        month: int,
        tz_offset: int = -480,
        min_text_length: int | None = None,
    ) -> str:
        """获取指定月份的每日推文统计数量。

        Args:
            year: 年份（用户本地时区），如 2026
            month: 月份 1-12（用户本地时区），如 2
            tz_offset: 时区偏移（分钟），JS getTimezoneOffset() 的值。
                       UTC+8（中国）为 -480，UTC 为 0。默认 -480
            min_text_length: 最小推文文本长度过滤（可选）
        """
        if not (1 <= month <= 12):
            return error_response("月份必须在 1-12 之间", "validation")

        try:
            from src.data_layer.provider import get_browse_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                stats = await get_browse_repo(session).get_daily_stats(
                    year=year,
                    month=month,
                    tz_offset=tz_offset,
                    min_text_length=min_text_length,
                )
                return success_response({
                    "year": year,
                    "month": month,
                    "tz_offset": tz_offset,
                    "daily_stats": stats,
                })
        except Exception as e:
            logger.error("get_daily_stats 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_authors_for_date(
        date: str,
        tz_offset: int = -480,
        min_text_length: int | None = None,
    ) -> str:
        """获取指定日期的发文作者列表及推文数。

        Args:
            date: 用户本地日期，YYYY-MM-DD 格式，如 "2026-02-24"
            tz_offset: 时区偏移（分钟），UTC+8（中国）为 -480。默认 -480
            min_text_length: 最小推文文本长度过滤（可选）
        """
        try:
            from src.data_layer.provider import get_browse_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                authors = await get_browse_repo(session).get_authors(
                    date=date,
                    tz_offset=tz_offset,
                    min_text_length=min_text_length,
                )
                return success_response({
                    "date": date,
                    "tz_offset": tz_offset,
                    "authors": authors,
                    "count": len(authors),
                })
        except ValueError as e:
            return error_response(f"日期格式无效: {e}", "validation")
        except Exception as e:
            logger.error("get_authors_for_date 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def browse_tweets(
        date: str,
        author: str | None = None,
        page: int = 1,
        page_size: int = 20,
        tz_offset: int = -480,
        min_text_length: int | None = None,
    ) -> str:
        """按日期/作者浏览推文（含摘要翻译），支持分页。

        Args:
            date: 用户本地日期，YYYY-MM-DD 格式，如 "2026-02-24"
            author: 按作者用户名筛选（可选，大小写不敏感）
            page: 页码（从 1 开始），默认 1
            page_size: 每页条数，默认 20
            tz_offset: 时区偏移（分钟），UTC+8（中国）为 -480。默认 -480
            min_text_length: 最小推文文本长度过滤（可选）
        """
        if page < 1:
            return error_response("页码必须 >= 1", "validation")

        # 钳制 page_size 到合理范围
        clamped_page_size = min(max(page_size, 1), 100)

        try:
            from src.data_layer.provider import get_browse_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                items, total = await get_browse_repo(session).get_tweets(
                    date=date,
                    author=author,
                    page=page,
                    page_size=clamped_page_size,
                    tz_offset=tz_offset,
                    min_text_length=min_text_length,
                )
                total_pages = (
                    (total + clamped_page_size - 1) // clamped_page_size if total > 0 else 0
                )
                return success_response({
                    "items": items,
                    "total": total,
                    "count": len(items),
                    "page": page,
                    "page_size": clamped_page_size,
                    "total_pages": total_pages,
                    "date": date,
                    "author": author,
                })
        except ValueError as e:
            return error_response(f"日期格式无效: {e}", "validation")
        except Exception as e:
            logger.error("browse_tweets 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")
