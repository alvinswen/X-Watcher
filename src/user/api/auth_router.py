"""认证 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.user.domain.schemas import LoginRequest, LoginResponse
from src.user.infrastructure.repository import UserRepository
from src.user.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> LoginResponse:
    """用户登录，返回 JWT Token。"""
    repo = UserRepository(session)
    auth = AuthService()

    # 查询用户（使用 ORM 对象以获取 password_hash）
    user_orm = await repo.get_user_orm_by_email(request.email)
    if user_orm is None or user_orm.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 验证密码
    if not await auth.verify_password(request.password, user_orm.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 生成 JWT Token
    token = auth.create_jwt_token(
        user_id=user_orm.id,
        email=user_orm.email,
        is_admin=user_orm.is_admin,
    )

    return LoginResponse(access_token=token)
