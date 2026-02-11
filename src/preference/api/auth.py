"""API 认证依赖模块。

提供 API Key 认证功能用于管理员 API。
"""

import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


async def verify_admin_api_key(
    x_api_key: str | None = Header(None),
) -> bool:
    """验证管理员 API Key。

    从 X-API-Key 请求头读取并验证 API Key。
    如果验证失败，抛出 403 Forbidden 异常。

    Args:
        x_api_key: 从 X-API-Key 请求头读取的 API Key

    Returns:
        bool: 验证成功返回 True

    Raises:
        HTTPException: 如果 API Key 无效或缺失
    """
    # 从环境变量读取预期的 API Key
    expected_key = os.getenv("ADMIN_API_KEY")

    # 如果未设置 ADMIN_API_KEY，则禁用认证（开发环境）
    if expected_key is None:
        return True

    # 如果 x_api_key 为 None，说明请求头不存在
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="缺少 API Key，请在请求头中提供 X-API-Key"
        )

    # 验证 API Key
    if x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的 API Key"
        )

    return True


# 依赖类型别名，用于 FastAPI 路由
AdminAuthDep = Annotated[bool, Depends(verify_admin_api_key)]
