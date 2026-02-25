"""MCP Server 主模块。

创建 FastMCP 实例，注册所有工具和资源，提供服务入口函数。
"""

import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from src.mcp.auth import auth_context
from src.mcp.lifespan import init_database, init_mcp_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def mcp_lifespan(server: FastMCP):
    """MCP 服务生命周期管理。

    启动时初始化数据库，关闭时清理资源。
    日志初始化在 run_mcp_server() 中已完成（需在 lifespan 之前）。
    """
    logger.info(
        "MCP Server 启动: transport=%s, admin=%s",
        auth_context.transport,
        auth_context.is_admin,
    )
    init_database()
    logger.info("MCP Server 就绪")
    yield
    logger.info("MCP Server 关闭")


def create_mcp_server(
    host: str = "0.0.0.0",
    port: int = 8001,
) -> FastMCP:
    """创建并配置 FastMCP 实例。

    Args:
        host: SSE 模式监听地址
        port: SSE 模式监听端口
    """
    mcp = FastMCP(
        "x-watcher",
        instructions=(
            "X-watcher 是面向 AI Agent 的 X(Twitter) 平台智能信息监控服务。"
            "你可以通过这些工具查询推文 feed、搜索推文、浏览每日统计、"
            "管理监控主题、查看系统状态等。"
            "时间参数使用 ISO 8601 格式（如 2026-02-24T00:00:00Z）。"
        ),
        lifespan=mcp_lifespan,
        host=host,
        port=port,
    )

    # 注册 Phase 1 工具（User 级只读：Feed、Browse、Status）
    from src.mcp.tools import browse_tools, feed_tools, status_tools

    feed_tools.register(mcp)
    browse_tools.register(mcp)
    status_tools.register(mcp)

    # 注册 Phase 2 工具（User 级：Topic 管理、分析）
    from src.mcp.tools import analytics_tools, topic_tools

    topic_tools.register(mcp)
    analytics_tools.register(mcp)

    # 注册 Phase 3 工具（Admin 级：关注管理、抓取、调度、摘要）
    from src.mcp.tools import admin_tools

    admin_tools.register(mcp)

    # 注册资源
    from src.mcp.resources import providers

    providers.register(mcp)

    return mcp


def run_mcp_server(
    transport: str = "stdio",
    host: str = "0.0.0.0",
    port: int = 8001,
    api_key: str | None = None,
) -> None:
    """启动 MCP Server。

    Args:
        transport: 传输模式（"stdio" 或 "sse"）
        host: SSE 模式监听地址
        port: SSE 模式监听端口
        api_key: SSE 模式下的 API Key（用于权限验证）
    """
    # 1. 初始化日志（必须在创建 FastMCP 之前）
    init_mcp_logging(stderr_only=(transport == "stdio"))

    # 2. 配置认证上下文
    auth_context.configure(transport=transport, api_key=api_key)

    # 3. 创建 MCP Server（host/port 传给构造函数供 SSE 使用）
    mcp = create_mcp_server(host=host, port=port)

    # 4. 启动服务
    if transport == "stdio":
        logger.info("MCP Server 以 stdio 模式启动")
        mcp.run(transport="stdio")
    elif transport == "sse":
        logger.info("MCP Server 以 SSE 模式启动: %s:%s", host, port)
        mcp.run(transport="sse")
    else:
        raise ValueError(f"不支持的传输模式: {transport}")
