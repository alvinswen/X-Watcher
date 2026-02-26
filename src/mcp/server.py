"""MCP Server 主模块。

创建 FastMCP 实例，注册所有工具和资源，提供服务入口函数。
"""

import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from src.mcp.auth import configure_transport, get_transport, is_admin
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
        get_transport(),
        is_admin(),
    )
    init_database()
    logger.info("MCP Server 就绪")
    yield
    logger.info("MCP Server 关闭")


def create_mcp_server(
    host: str = "0.0.0.0",
    port: int = 8001,
    *,
    use_auth: bool = False,
) -> FastMCP:
    """创建并配置 FastMCP 实例。

    Args:
        host: HTTP 模式监听地址
        port: HTTP 模式监听端口
        use_auth: 是否启用 per-request 认证（HTTP 模式）
    """
    kwargs: dict = {
        "name": "x-watcher",
        "instructions": (
            "X-watcher 是面向 AI Agent 的 X(Twitter) 平台智能信息监控服务。"
            "你可以通过这些工具查询推文 feed、搜索推文、浏览每日统计、"
            "管理监控主题、查看系统状态等。"
            "时间参数使用 ISO 8601 格式（如 2026-02-24T00:00:00Z）。"
        ),
        "lifespan": mcp_lifespan,
        "host": host,
        "port": port,
    }

    if use_auth:
        from mcp.server.auth.settings import AuthSettings
        from pydantic import AnyHttpUrl

        from src.mcp.token_verifier import XWatcherTokenVerifier

        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(f"http://{host}:{port}"),
            resource_server_url=AnyHttpUrl(f"http://{host}:{port}"),
        )
        kwargs["auth"] = auth_settings
        kwargs["token_verifier"] = XWatcherTokenVerifier()
        logger.info("MCP per-request 认证已启用")

    mcp = FastMCP(**kwargs)

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
        host: HTTP 模式监听地址
        port: HTTP 模式监听端口
        api_key: 已弃用，保留参数兼容性。HTTP 模式使用 per-request 认证。
    """
    if api_key:
        logger.warning(
            "api_key 参数已弃用，HTTP 模式现在使用 per-request Bearer token 认证。"
            "请通过 ADMIN_API_KEY 环境变量或数据库 API Key 配置访问权限。"
        )

    # 1. 初始化日志（必须在创建 FastMCP 之前）
    init_mcp_logging(stderr_only=(transport == "stdio"))

    # 2. 配置传输模式
    configure_transport(transport)

    # 3. 创建 MCP Server
    #    stdio 模式：不启用 auth（本地使用，默认 admin）
    #    HTTP 模式：启用 per-request auth
    use_auth = transport != "stdio"
    mcp = create_mcp_server(host=host, port=port, use_auth=use_auth)

    # 4. 启动服务
    if transport == "stdio":
        logger.info("MCP Server 以 stdio 模式启动")
        mcp.run(transport="stdio")
    elif transport == "sse":
        logger.info("MCP Server 以 SSE 模式启动: %s:%s", host, port)
        mcp.run(transport="sse")
    else:
        raise ValueError(f"不支持的传输模式: {transport}")
