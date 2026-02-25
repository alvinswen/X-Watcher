"""MCP 认证上下文管理。

管理 MCP 服务的认证状态：
- stdio 模式：默认以 admin 身份运行（本地使用场景）
- SSE 模式：通过启动参数传递 API Key，验证后确定权限级别
"""

import logging

logger = logging.getLogger(__name__)


class MCPAuthContext:
    """MCP 认证上下文。

    在 MCP 服务启动时根据传输模式和 API Key 配置确定权限级别。
    所有工具调用共享同一认证上下文（单进程单客户端模型）。
    """

    def __init__(self) -> None:
        self._is_admin: bool = True
        self._transport: str = "stdio"
        self._user_name: str = "mcp_admin"

    def configure(self, transport: str, api_key: str | None = None) -> None:
        """根据传输模式和 API Key 配置认证上下文。

        Args:
            transport: 传输模式（"stdio" 或 "sse"）
            api_key: SSE 模式下的 API Key（可选）
        """
        self._transport = transport

        if transport == "stdio":
            # stdio 模式：本地使用，默认 admin
            self._is_admin = True
            self._user_name = "mcp_admin"
            logger.info("MCP 认证：stdio 模式，admin 权限")
        elif transport == "sse":
            if api_key:
                self._is_admin = self._validate_api_key(api_key)
                if self._is_admin:
                    self._user_name = "mcp_admin"
                    logger.info("MCP 认证：SSE 模式，API Key 验证通过，admin 权限")
                else:
                    self._user_name = "mcp_user"
                    logger.info("MCP 认证：SSE 模式，API Key 验证通过，普通用户权限")
            else:
                # 无 API Key：非 admin
                self._is_admin = False
                self._user_name = "mcp_user"
                logger.info("MCP 认证：SSE 模式，无 API Key，普通用户权限")

    @property
    def is_admin(self) -> bool:
        return self._is_admin

    @property
    def transport(self) -> str:
        return self._transport

    @property
    def user_name(self) -> str:
        return self._user_name

    @staticmethod
    def _validate_api_key(api_key: str) -> bool:
        """验证 API Key 是否具有 admin 权限。

        优先检查 ADMIN_API_KEY 环境变量，再查询数据库中的用户 API Key。
        """
        from src.config import get_settings

        settings = get_settings()

        # 检查 ADMIN_API_KEY 环境变量
        if settings.admin_api_key and api_key == settings.admin_api_key:
            return True

        # 查询数据库中的用户 API Key（同步查询，仅在启动时执行一次）
        try:
            import hashlib

            from sqlalchemy import select

            from src.database.models import ApiKey, User, get_engine

            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            eng = get_engine()

            with eng.connect() as conn:
                result = conn.execute(
                    select(User.is_admin).select_from(
                        ApiKey.__table__.join(User.__table__, ApiKey.user_id == User.id)
                    ).where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_active == True,  # noqa: E712
                    )
                )
                row = result.first()
                if row:
                    return bool(row.is_admin)
        except Exception as e:
            logger.warning("API Key 数据库验证失败: %s", e)

        return False


# 全局认证上下文单例
auth_context = MCPAuthContext()


def require_admin() -> str | None:
    """检查当前是否具有 admin 权限。

    Returns:
        None 表示有权限；非 None 返回错误 JSON 字符串。
    """
    if not auth_context.is_admin:
        from src.mcp.helpers import error_response

        return error_response("需要管理员权限", "permission")
    return None
