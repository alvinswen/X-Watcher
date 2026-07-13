"""用户管理领域模型。

定义用户和 API Key 相关的 Pydantic 领域模型，与 ORM 模型分离。
"""

from datetime import datetime

from pydantic import BaseModel


class UserDomain(BaseModel):
    """用户领域模型。"""

    id: int
    name: str
    email: str
    is_admin: bool
    created_at: datetime



class ApiKeyInfo(BaseModel):
    """API Key 信息领域模型。"""

    id: int
    user_id: int
    key_prefix: str
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None



BOOTSTRAP_ADMIN = UserDomain(
    id=0,
    name="bootstrap",
    email="bootstrap@system",
    is_admin=True,
    created_at=datetime.min,
)
