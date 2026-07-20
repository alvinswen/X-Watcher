"""认证 API 路由。"""

import logging
import math

from fastapi import APIRouter, HTTPException, status

from src.data_layer.provider import get_user_repo
from src.shared.error_messages import LOGIN_RATE_LIMITED_TMPL
from src.user.domain.schemas import LoginRequest, LoginResponse
from src.user.services.auth_service import AuthService
from src.user.services.login_rate_limiter import login_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
) -> LoginResponse:
    """用户登录，返回 JWT Token。"""
    remaining = login_rate_limiter.check_locked()
    if remaining is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=LOGIN_RATE_LIMITED_TMPL.format(minutes=math.ceil(remaining / 60)),
            headers={"Retry-After": str(math.ceil(remaining))},
        )

    repo = get_user_repo()
    auth = AuthService()

    # 查询用户域对象(id/email/is_admin 供 JWT)+ password_hash(供密码验证)
    user = await repo.get_user_by_email(request.email)
    password_hash = await repo.get_password_hash_by_email(request.email)
    if user is None or password_hash is None:
        login_rate_limiter.record_failure()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 验证密码
    if not await auth.verify_password(request.password, password_hash):
        login_rate_limiter.record_failure()
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

    login_rate_limiter.record_success()
    return LoginResponse(access_token=token)
