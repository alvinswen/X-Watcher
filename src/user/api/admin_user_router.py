"""管理员用户操作 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.user.domain.schemas import (
    CreateUserRequest,
    CreateUserResponse,
    ResetPasswordResponse,
    UserResponse,
)
from src.user.infrastructure.repository import DuplicateError, NotFoundError
from src.user.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


@router.post(
    "",
    response_model=CreateUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    request: CreateUserRequest,
    admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> CreateUserResponse:
    """创建用户（管理员）。"""
    service = UserService(session)
    try:
        user, temp_password, raw_key = await service.create_user(
            request.name, request.email
        )
    except DuplicateError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已被注册",
        )
    return CreateUserResponse(
        user=UserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            is_admin=user.is_admin,
            created_at=user.created_at,
        ),
        temp_password=temp_password,
        api_key=raw_key,
    )


@router.get("", response_model=list[UserResponse])
async def list_users(
    admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[UserResponse]:
    """列出所有用户（管理员）。"""
    service = UserService(session)
    users = await service.list_users()
    return [
        UserResponse(
            id=u.id,
            name=u.name,
            email=u.email,
            is_admin=u.is_admin,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post(
    "/{user_id}/reset-password",
    response_model=ResetPasswordResponse,
)
async def reset_password(
    user_id: int,
    admin: UserDomain = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> ResetPasswordResponse:
    """重置用户密码（管理员）。"""
    service = UserService(session)
    try:
        temp_password = await service.reset_password(user_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    return ResetPasswordResponse(temp_password=temp_password)
