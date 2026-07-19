"""配置验证 API 路由。

提供运行时配置验证端点，检查 Twitter API、数据库的健康状态。
"""

from typing import Any

from fastapi import APIRouter, Depends

from src.shared.connectivity_check import check_database, check_twitter_api
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

router = APIRouter(prefix="/api/admin/config", tags=["config"])


@router.get("/validate")
async def validate_config(
    _admin: UserDomain = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """验证当前配置的服务连通性。

    返回各服务的健康状态：
    - twitter_api: Twitter API 状态
    - database: 数据库连接状态
    """
    twitter_result = await check_twitter_api()
    db_result = check_database()

    return {
        "twitter_api": twitter_result,
        "database": db_result,
    }
