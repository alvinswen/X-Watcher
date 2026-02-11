"""统一认证中间件。

提供 get_current_user 和 get_current_admin_user FastAPI 依赖。
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.async_session import get_async_session
from src.user.domain.models import BOOTSTRAP_ADMIN, UserDomain
from src.user.infrastructure.repository import UserRepository
from src.user.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# FastAPI security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

_auth_service = AuthService()


async def get_current_user(
    api_key: Annotated[str | None, Depends(api_key_header)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    session: AsyncSession = Depends(get_async_session),
) -> UserDomain:
    """统一认证依赖：优先 API Key，其次 JWT。两者均无效则 401。"""
    repo = UserRepository(session)

    # 1. 尝试 API Key 认证
    if api_key:
        key_hash = _auth_service.hash_api_key(api_key)
        result = await repo.get_active_key_by_hash(key_hash)
        if result is not None:
            key_info, user_id = result
            # 更新 last_used_at
            await repo.update_key_last_used(key_info.id)
            user = await repo.get_user_by_id(user_id)
            if user:
                logger.debug(f"API Key 认证成功: user_id={user.id}")
                return user
        logger.warning("API Key 认证失败: 无效或非活跃的 Key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
        )

    # 2. 尝试 JWT 认证
    if bearer:
        try:
            payload = _auth_service.decode_jwt_token(bearer.credentials)
            user_id = payload.get("sub")
            if user_id is not None:
                user = await repo.get_user_by_id(int(user_id))
                if user:
                    logger.debug(f"JWT 认证成功: user_id={user.id}")
                    return user
            logger.warning("JWT 认证失败: 用户不存在")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 Token",
            )
        except HTTPException:
            raise
        except Exception as e:
            error_type = type(e).__name__
            if "ExpiredSignature" in error_type:
                logger.warning("JWT 认证失败: Token 已过期")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token 已过期",
                )
            logger.warning(f"JWT 认证失败: {error_type}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 Token",
            )

    # 3. 无凭证
    logger.warning("认证失败: 缺少认证凭证")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少认证凭证",
    )


async def get_current_admin_user(
    api_key: Annotated[str | None, Depends(api_key_header)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    session: AsyncSession = Depends(get_async_session),
) -> UserDomain:
    """管理员认证依赖。

    先尝试用户认证，回退到 ADMIN_API_KEY 环境变量。
    ADMIN_API_KEY 认证时返回 BOOTSTRAP_ADMIN 虚拟用户（id=0）。
    """
    settings = get_settings()

    # 1. 先尝试标准用户认证（API Key 或 JWT）
    if api_key or bearer:
        try:
            user = await get_current_user(
                api_key=api_key, bearer=bearer, session=session
            )
            if not user.is_admin:
                logger.warning(f"权限不足: user_id={user.id} 不是管理员")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="需要管理员权限",
                )
            return user
        except HTTPException as e:
            # 如果是 API Key 且匹配 ADMIN_API_KEY，使用引导模式
            if (
                e.status_code == status.HTTP_401_UNAUTHORIZED
                and api_key
                and settings.admin_api_key
                and api_key == settings.admin_api_key
            ):
                logger.debug("ADMIN_API_KEY 引导认证成功")
                return BOOTSTRAP_ADMIN
            raise

    # 2. 无凭证但检查 ADMIN_API_KEY 头
    # 这种情况不应该发生（如果有 X-API-Key 头，api_key 不为 None）
    logger.warning("管理员认证失败: 缺少认证凭证")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少认证凭证",
    )
