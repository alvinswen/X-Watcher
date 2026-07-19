"""公共 Pydantic 基类测试。"""

import json
from datetime import datetime, timezone, timedelta, UTC

from src.shared.schemas import UTCDatetimeModel


class _TestModel(UTCDatetimeModel):
    """测试用的 UTCDatetimeModel 子类。"""

    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestUTCDatetimeSerialization:
    """测试 UTCDatetimeModel 的 datetime 序列化行为。"""

    def test_naive_datetime_gets_utc_marker(self):
        """测试 naive datetime 序列化时添加 UTC 标记。"""
        model = _TestModel(created_at=datetime(2026, 2, 22, 10, 30, 0))
        data = json.loads(model.model_dump_json())

        assert "+00:00" in data["created_at"]
        assert data["created_at"] == "2026-02-22T10:30:00+00:00"

    def test_aware_datetime_preserves_timezone(self):
        """测试 timezone-aware datetime 保留原始时区。"""
        cst = timezone(timedelta(hours=8))
        model = _TestModel(created_at=datetime(2026, 2, 22, 18, 30, 0, tzinfo=cst))
        data = json.loads(model.model_dump_json())

        assert "+08:00" in data["created_at"]

    def test_utc_datetime_serialized_correctly(self):
        """测试已有 UTC 时区的 datetime 序列化正确。"""
        model = _TestModel(
            created_at=datetime(2026, 2, 22, 10, 30, 0, tzinfo=UTC)
        )
        data = json.loads(model.model_dump_json())

        assert "+00:00" in data["created_at"]

    def test_none_datetime_serialized_as_null(self):
        """测试 None datetime 序列化为 null。"""
        model = _TestModel(created_at=None)
        data = json.loads(model.model_dump_json())

        assert data["created_at"] is None

    def test_multiple_datetime_fields(self):
        """测试多个 datetime 字段都正确序列化。"""
        model = _TestModel(
            created_at=datetime(2026, 1, 1, 0, 0, 0),
            updated_at=datetime(2026, 2, 22, 12, 0, 0),
        )
        data = json.loads(model.model_dump_json())

        assert "+00:00" in data["created_at"]
        assert "+00:00" in data["updated_at"]

    def test_datetime_with_microseconds(self):
        """测试带微秒的 datetime 序列化。"""
        model = _TestModel(
            created_at=datetime(2026, 2, 22, 10, 30, 0, 123456)
        )
        data = json.loads(model.model_dump_json())

        assert "123456" in data["created_at"]
        assert "+00:00" in data["created_at"]
