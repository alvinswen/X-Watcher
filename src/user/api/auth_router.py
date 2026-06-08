"""认证 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.user.domain.schemas import LoginRequest, LoginResponse
from src.data_layer.provider import get_user_repo
from src.user.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> LoginResponse:
    """用户登录，返回 JWT Token。"""
    repo = get_user_repo(session)
    auth = AuthService()

    # 查询用户域对象(id/email/is_admin 供 JWT)+ password_hash(供密码验证)
    user = await repo.get_user_by_email(request.email)
    password_hash = await repo.get_password_hash_by_email(request.email)
    if user is None or password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 验证密码
    if not await auth.verify_password(request.password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 生成 JWT Token
    token = auth.create_jwt_token(
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )

    return LoginResponse(access_token=token)
