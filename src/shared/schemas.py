"""公共 Pydantic 基类。

提供 UTC datetime 序列化支持，解决 SQLite naive datetime 的时区问题。
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    field_serializer,
)


class UTCDatetimeModel(BaseModel):
    """带 UTC datetime 序列化的 Pydantic 基类。

    SQLite 不存储时区信息，ORM 返回 naive datetime（实际为 UTC）。
    本基类确保所有 datetime 字段序列化为 JSON 时带上 UTC 时区标记（+00:00），
    避免前端 JavaScript ``new Date()`` 将其误解析为本地时间。
    """

    @field_serializer("*", mode="wrap", when_used="json")
    def _serialize_datetime_utc(
        self,
        value: Any,
        handler: SerializerFunctionWrapHandler,
    ) -> Any:
        """序列化顶层 datetime 字段，并让其他字段沿用 Pydantic 默认行为。"""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc).isoformat()
            return value.isoformat()
        return handler(value)


class ErrorResponse(BaseModel):
    """错误响应声明模型。"""

    detail: str = Field(..., description="错误详情")
