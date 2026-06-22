"""MCP 分析工具。

提供 get_posting_frequency 工具，经 provider get_analytics_repo 路由（file/sqlalchemy）。
"""

import logging

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import error_response, success_response

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册分析相关 MCP 工具。"""

    @mcp.tool()
    async def get_posting_frequency(
        topic_id: int,
        tz_offset: int = -480,
        slots: int = 50,
    ) -> str:
        """获取主题内账号的发文频率分布（30分钟时间槽）。

        返回最近 N 个半小时时段的推文数量分布（稀疏格式，只返回有推文的时段）。

        Args:
            topic_id: 主题 ID
            tz_offset: 时区偏移（分钟），UTC+8（中国）为 -480。默认 -480
            slots: 返回多少个半小时时段，默认 50（即最近 25 小时）
        """
        if slots < 1 or slots > 500:
            return error_response("slots 必须在 1-500 之间", "validation")

        try:
            from src.data_layer.provider import get_analytics_repo
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = get_analytics_repo(session)
                result = await repo.get_posting_frequency(
                    topic_id=topic_id,
                    tz_offset=tz_offset,
                    slots=slots,
                )
                return success_response(result)
        except Exception as e:
            logger.error("get_posting_frequency 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")
