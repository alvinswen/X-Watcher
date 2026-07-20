"""MCP Token 验证器。

实现 mcp.server.auth.provider.TokenVerifier 协议，
支持 per-request 级别的 Bearer token 验证。
"""

import hashlib
import logging
import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)


class XWatcherTokenVerifier(TokenVerifier):
    """X-Watcher MCP Token 验证器。

    验证逻辑：
    1. 检查 ADMIN_API_KEY 环境变量 → admin + user scope
    2. 查询文件层 user store 的用户 API Key → 根据用户 is_admin 决定 scope
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
        if settings.admin_api_key and secrets.compare_digest(
            token.encode("utf-8"), settings.admin_api_key.encode("utf-8")
        ):
            logger.debug("Token 验证通过: admin API key")
            return AccessToken(
                token=token,
                client_id="admin",
                scopes=["admin", "user", "subjects:write"],
            )

        # 2. 查询文件层 user store 的用户 API Key
        try:
            from src.data_layer.provider import get_user_repo

            key_hash = hashlib.sha256(token.encode()).hexdigest()
            repo = get_user_repo()
            key_result = await repo.get_active_key_by_hash(key_hash)
            if key_result is not None:
                _key_info, user_id = key_result
                user = await repo.get_user_by_id(user_id)
                if user is not None:
                    is_admin = bool(user.is_admin)
                    user_name = user.name or "mcp_user"
                    scopes = ["admin", "user", "subjects:write"] if is_admin else ["user"]
                    logger.debug(
                        "Token 验证通过: 文件层用户 %s (admin=%s)",
                        user_name,
                        is_admin,
                    )
                    return AccessToken(
                        token=token,
                        client_id=user_name,
                        scopes=scopes,
                    )
        except Exception as e:
            logger.warning("Token 用户 API Key 验证失败: %s", e)

        logger.debug("Token 验证失败: 无匹配的 API key")
        return None
