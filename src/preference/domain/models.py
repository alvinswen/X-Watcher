"""偏好管理领域模型。

定义偏好管理相关的 Pydantic 领域模型，与 ORM 模型分离。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class FilterType(str, Enum):
    """过滤类型枚举。

    定义支持的内容过滤规则类型。
    """

    KEYWORD = "keyword"  # 关键词过滤
    HASHTAG = "hashtag"  # 话题标签过滤
    CONTENT_TYPE = "content_type"  # 内容类型过滤（如转推、媒体）


class SortType(str, Enum):
    """排序类型枚举。

    定义支持的新闻流排序方式。
    """

    TIME = "time"  # 按时间倒序
    RELEVANCE = "relevance"  # 按相关性排序
    PRIORITY = "priority"  # 按人物优先级排序


class ScraperScheduleConfig(BaseModel):
    """调度配置领域模型。"""

    id: int
    interval_seconds: int
    next_run_time: datetime | None
    updated_at: datetime
    updated_by: str

    @classmethod
    def from_orm(cls, orm_obj) -> "ScraperScheduleConfig":
        """从 ORM 模型转换为领域模型。"""
        return cls(
            id=orm_obj.id,
            interval_seconds=orm_obj.interval_seconds,
            next_run_time=orm_obj.next_run_time,
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
        )


class TwitterFollow(BaseModel):
    """用户关注领域模型。

    表示用户选择的 Twitter 关注账号。
    """

    id: int = Field(..., description="关注记录 ID")
    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="Twitter 用户名")
    priority: int = Field(..., ge=1, le=10, description="优先级（1-10）")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @classmethod
    def from_orm(cls, orm_obj: "TwitterFollowORM") -> "TwitterFollow":
        """从 ORM 模型转换为领域模型。

        Args:
            orm_obj: SQLAlchemy ORM 模型实例

        Returns:
            领域模型实例
        """
        return cls(
            id=orm_obj.id,
            user_id=orm_obj.user_id,
            username=orm_obj.username,
            priority=orm_obj.priority,
            created_at=orm_obj.created_at,
            updated_at=orm_obj.updated_at,
        )


class FilterRule(BaseModel):
    """过滤规则领域模型。

    表示用户配置的内容过滤规则。
    """

    id: str = Field(..., description="过滤规则 ID（UUID）")
    user_id: int = Field(..., description="用户 ID")
    filter_type: FilterType = Field(..., description="过滤类型")
    value: str = Field(..., description="过滤值")
    created_at: datetime = Field(..., description="创建时间")

    @classmethod
    def from_orm(cls, orm_obj: "FilterRuleORM") -> "FilterRule":
        """从 ORM 模型转换为领域模型。

        Args:
            orm_obj: SQLAlchemy ORM 模型实例

        Returns:
            领域模型实例
        """
        # 将字符串类型的 filter_type 转换为枚举
        filter_type = FilterType(orm_obj.filter_type)
        return cls(
            id=orm_obj.id,
            user_id=orm_obj.user_id,
            filter_type=filter_type,
            value=orm_obj.value,
            created_at=orm_obj.created_at,
        )
