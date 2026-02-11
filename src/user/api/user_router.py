"""用户自身操作 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_async_session
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain
from src.user.domain.schemas import (
    ApiKeyResponse,
    ChangePasswordRequest,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    UserResponse,
)
from src.user.infrastructure.repository import NotFoundError
from src.user.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: UserDomain = Depends(get_current_user),
) -> UserResponse:
    """获取当前用户信息。"""
    return UserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        is_admin=current_user.is_admin,
        created_at=current_user.created_at,
    )


@router.post(
    "/me/api-keys",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: CreateApiKeyRequest = None,
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> CreateApiKeyResponse:
    """创建新的 API Key。"""
    if request is None:
        request = CreateApiKeyRequest()
    service = UserService(session)
    key_info, raw_key = await service.create_api_key(current_user.id, request.name)
    return CreateApiKeyResponse(
        id=key_info.id,
        key=raw_key,
        key_prefix=key_info.key_prefix,
        name=key_info.name,
    )


@router.get("/me/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ApiKeyResponse]:
    """列出当前用户的 API Key。"""
    service = UserService(session)
    keys = await service.list_api_keys(current_user.id)
    return [
        ApiKeyResponse(
            id=k.id,
            key_prefix=k.key_prefix,
            name=k.name,
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.delete("/me/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: int,
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """撤销 API Key。"""
    service = UserService(session)
    try:
        await service.revoke_api_key(current_user.id, key_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key 不存在",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/me/password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: UserDomain = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """修改密码。"""
    service = UserService(session)
    try:
        await service.change_password(
            current_user.id, request.old_password, request.new_password
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码不正确",
        )
    return {"message": "密码修改成功"}
