"""MCP 认证上下文管理。

Per-request 认证模型：
- stdio 模式：默认以 admin 身份运行（本地使用场景），无需 token
- HTTP 模式（SSE/StreamableHTTP）：每个请求通过 Bearer token 独立认证，
  由 FastMCP 内置 auth 中间件链处理，权限信息存储在 ContextVar 中
"""

import logging

logger = logging.getLogger(__name__)

# 当前传输模式
_transport: str = "stdio"


def configure_transport(transport: str) -> None:
    """设置当前传输模式。

    Args:
        transport: 传输模式（"stdio", "sse", "streamable-http"）
    """
    global _transport
    _transport = transport
    logger.info("MCP 传输模式: %s", transport)


def get_transport() -> str:
    """获取当前传输模式。"""
    return _transport


def is_admin() -> bool:
    """检查当前请求是否具有 admin 权限。

    - stdio 模式：始终返回 True（本地使用，默认 admin）
    - HTTP 模式：从 ContextVar 中读取当前请求的 AccessToken，检查 scopes
    """
    if _transport == "stdio":
        return True

    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    if token is None:
        return False
    return "admin" in token.scopes


def get_user_name() -> str:
    """获取当前请求的用户名。

    - stdio 模式：返回 "mcp_admin"
    - HTTP 模式：从 ContextVar 中读取当前请求的 AccessToken 的 client_id
    """
    if _transport == "stdio":
        return "mcp_admin"

    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    if token is None:
        return "anonymous"
    return token.client_id


def require_admin() -> str | None:
    """检查当前请求是否具有 admin 权限。

    Returns:
        None 表示有权限；非 None 返回错误 JSON 字符串。
    """
    if not is_admin():
        from src.mcp.helpers import error_response

        return error_response("需要管理员权限", "permission")
    return None
