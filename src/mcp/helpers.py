"""MCP 工具通用辅助函数。

提供 JSON 响应序列化、datetime 处理等工具函数。
"""

import json
from datetime import datetime, timezone


def _default_serializer(obj: object) -> str:
    """JSON 默认序列化器：处理 datetime 等非基础类型。"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def success_response(data: object) -> str:
    """构造成功响应 JSON 字符串。"""
    return json.dumps(
        {"success": True, "data": data},
        ensure_ascii=False,
        default=_default_serializer,
    )


def parse_datetime(value: str) -> datetime:
    """解析 ISO 8601 日期时间字符串，无时区时默认 UTC。

    Args:
        value: ISO 8601 格式字符串，如 "2026-02-24T00:00:00Z"

    Returns:
        时区感知的 datetime 对象

    Raises:
        ValueError: 解析失败时抛出
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_datetime_optional(value: str | None) -> datetime | None:
    """解析可选的 ISO 8601 日期时间字符串。

    Args:
        value: ISO 8601 格式字符串或 None

    Returns:
        时区感知的 datetime 对象，或 None
    """
    if not value:
        return None
    return parse_datetime(value)


def error_response(message: str, error_type: str = "internal") -> str:
    """构造错误响应 JSON 字符串。

    Args:
        message: 错误描述
        error_type: 错误类型（validation / not_found / permission / internal）
    """
    return json.dumps(
        {"success": False, "error": message, "error_type": error_type},
        ensure_ascii=False,
    )


async def resolve_user_list(usernames: str | None) -> list[str]:
    """解析逗号分隔的用户名，或获取所有活跃关注账号。"""
    if usernames:
        return [u.strip() for u in usernames.split(",") if u.strip()]

    from src.database.async_session import get_async_session_maker
    from src.data_layer.provider import get_follows_repo

    session_maker = get_async_session_maker()
    async with session_maker() as session:
        repo = get_follows_repo(session)
        follows = await repo.get_active_follows()
        return [f.username for f in follows]
