"""公共 Pydantic 基类。

提供 UTC datetime 序列化支持，解决 SQLite naive datetime 的时区问题。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict


class UTCDatetimeModel(BaseModel):
    """带 UTC datetime 序列化的 Pydantic 基类。

    SQLite 不存储时区信息，ORM 返回 naive datetime（实际为 UTC）。
    本基类确保所有 datetime 字段序列化为 JSON 时带上 UTC 时区标记（+00:00），
    避免前端 JavaScript ``new Date()`` 将其误解析为本地时间。
    """

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: (
                v.replace(tzinfo=timezone.utc).isoformat()
                if v.tzinfo is None
                else v.isoformat()
            )
        }
    )
