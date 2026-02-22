"""关注列表管理领域模型。

定义关注列表管理相关的 Pydantic 领域模型，与 ORM 模型分离。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ScraperScheduleConfig(BaseModel):
    """调度配置领域模型。"""

    id: int
    interval_seconds: int
    next_run_time: datetime | None
    is_enabled: bool
    updated_at: datetime
    updated_by: str

    @classmethod
    def from_orm(cls, orm_obj) -> "ScraperScheduleConfig":
        """从 ORM 模型转换为领域模型。"""
        return cls(
            id=orm_obj.id,
            interval_seconds=orm_obj.interval_seconds,
            next_run_time=orm_obj.next_run_time,
            is_enabled=orm_obj.is_enabled,
            updated_at=orm_obj.updated_at,
            updated_by=orm_obj.updated_by,
        )


class ScraperFollow(BaseModel):
    """抓取账号领域模型。

    表示平台级的 Twitter 抓取账号配置。
    """

    id: int = Field(..., description="抓取账号 ID")
    username: str = Field(..., description="Twitter 用户名")
    added_at: datetime = Field(..., description="添加时间")
    reason: str = Field(..., description="添加理由")
    added_by: str = Field(..., description="添加人标识")
    is_active: bool = Field(..., description="是否启用")
    manual_limit: int | None = Field(None, description="手动推文数量限制")
    platform_user_id: str | None = Field(None, description="X 平台永久 user_id")

    @classmethod
    def from_orm(cls, orm_obj: "ScraperFollowORM") -> "ScraperFollow":
        """从 ORM 模型转换为领域模型。

        Args:
            orm_obj: SQLAlchemy ORM 模型实例

        Returns:
            领域模型实例
        """
        return cls(
            id=orm_obj.id,
            username=orm_obj.username,
            added_at=orm_obj.added_at,
            reason=orm_obj.reason,
            added_by=orm_obj.added_by,
            is_active=orm_obj.is_active,
            manual_limit=orm_obj.manual_limit,
            platform_user_id=orm_obj.platform_user_id,
        )
