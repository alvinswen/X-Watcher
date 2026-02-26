"""MCP Token 验证器。

实现 mcp.server.auth.provider.TokenVerifier 协议，
支持 per-request 级别的 Bearer token 验证。
"""

import hashlib
import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)


class XWatcherTokenVerifier(TokenVerifier):
    """X-Watcher MCP Token 验证器。

    验证逻辑：
    1. 检查 ADMIN_API_KEY 环境变量 → admin + user scope
    2. 查询数据库 api_keys 表 → 根据用户 is_admin 决定 scope
    3. 均未命中 → 返回 None（拒绝访问）
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        """验证 Bearer token 并返回访问权限信息。

        Args:
            token: Bearer token 字符串

        Returns:
            AccessToken 包含 scopes 信息，或 None 表示无效 token
        """
        if not token:
            return None

        # 1. 检查 ADMIN_API_KEY 环境变量
        from src.config import get_settings

        settings = get_settings()
        if settings.admin_api_key and token == settings.admin_api_key:
            logger.debug("Token 验证通过: admin API key")
            return AccessToken(
                token=token,
                client_id="admin",
                scopes=["admin", "user"],
            )

        # 2. 查询数据库中的用户 API Key
        try:
            from sqlalchemy import select

            from src.database.async_session import get_async_session_maker
            from src.database.models import ApiKey, User

            key_hash = hashlib.sha256(token.encode()).hexdigest()
            session_maker = get_async_session_maker()

            async with session_maker() as session:
                result = await session.execute(
                    select(User.is_admin, User.name).select_from(
                        ApiKey.__table__.join(
                            User.__table__, ApiKey.user_id == User.id
                        )
                    ).where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_active == True,  # noqa: E712
                    )
                )
                row = result.first()
                if row:
                    is_admin = bool(row.is_admin)
                    user_name = row.name or "mcp_user"
                    scopes = ["admin", "user"] if is_admin else ["user"]
                    logger.debug(
                        "Token 验证通过: 数据库用户 %s (admin=%s)",
                        user_name,
                        is_admin,
                    )
                    return AccessToken(
                        token=token,
                        client_id=user_name,
                        scopes=scopes,
                    )
        except Exception as e:
            logger.warning("Token 数据库验证失败: %s", e)

        logger.debug("Token 验证失败: 无匹配的 API key")
        return None
