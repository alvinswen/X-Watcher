"""公共 Pydantic 基类。

提供 UTC datetime 序列化支持，解决 SQLite naive datetime 的时区问题。
"""

from datetime import UTC, datetime
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
    # 禁写返回注解（含 -> Any）：Pydantic 会将其用于所有继承者字段的
    # serialization schema，导致既有 OpenAPI 字段 type/format 消失。
    def _serialize_datetime_utc(  # type: ignore[no-untyped-def]
        self, value: Any, handler: SerializerFunctionWrapHandler
    ):
        """序列化顶层 datetime 字段，并让其他字段沿用 Pydantic 默认行为。"""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC).isoformat()
            return value.isoformat()
        return handler(value)


class ErrorResponse(BaseModel):
    """错误响应声明模型。"""

    detail: str = Field(..., description="错误详情")


def _chg047_drill_probe() -> int:
    return "deliberately-red"  # mypy 必红 · 演习用后即删
