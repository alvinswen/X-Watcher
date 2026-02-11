"""用户管理 API Schema。

定义请求和响应的 Pydantic Schema。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求。"""

    email: str
    password: str


class CreateUserRequest(BaseModel):
    """创建用户请求（管理员操作）。"""

    name: str
    email: str


class CreateApiKeyRequest(BaseModel):
    """创建 API Key 请求。"""

    name: str = "default"


class ChangePasswordRequest(BaseModel):
    """修改密码请求。"""

    old_password: str
    new_password: str = Field(min_length=8)


class LoginResponse(BaseModel):
    """登录响应。"""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """用户信息响应。"""

    id: int
    name: str
    email: str
    is_admin: bool
    created_at: datetime


class CreateUserResponse(BaseModel):
    """创建用户响应（包含临时密码和 API Key）。"""

    user: UserResponse
    temp_password: str
    api_key: str


class CreateApiKeyResponse(BaseModel):
    """创建 API Key 响应。"""

    id: int
    key: str
    key_prefix: str
    name: str


class ApiKeyResponse(BaseModel):
    """API Key 信息响应。"""

    id: int
    key_prefix: str
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class ResetPasswordResponse(BaseModel):
    """重置密码响应。"""

    temp_password: str
