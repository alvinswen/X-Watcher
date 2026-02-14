"""关注列表管理 API 请求/响应模型。

定义 FastAPI 端点使用的 Pydantic 模型。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.shared.schemas import UTCDatetimeModel


def _normalize_username(username: str) -> str:
    """标准化 Twitter 用户名。

    去除开头的 @ 符号并转换为小写。

    Args:
        username: 原始用户名

    Returns:
        标准化后的用户名
    """
    return username.lstrip("@").lower()


class CreateFollowRequest(BaseModel):
    """创建关注请求模型。

    用于添加或恢复关注的 Twitter 账号。
    """

    username: str = Field(
        ...,
        min_length=1,
        max_length=15,
        description="Twitter 用户名（不含 @ 符号）",
    )

    @field_validator("username")
    @classmethod
    def validate_and_normalize_username(cls, v: str) -> str:
        """验证并标准化 Twitter 用户名。

        Twitter 用户名规则：
        - 1-15 字符
        - 只包含字母数字和下划线
        - 不能包含空格或特殊字符

        Args:
            v: 用户名

        Returns:
            标准化后的用户名

        Raises:
            ValueError: 如果用户名格式无效
        """
        normalized = _normalize_username(v)
        if not normalized:
            raise ValueError("用户名不能为空")

        # 检查长度（标准化后）
        if len(normalized) > 15:
            raise ValueError("用户名不能超过 15 个字符")

        # 检查是否只包含有效字符
        if not normalized.replace("_", "").isalnum():
            raise ValueError(
                "用户名只能包含字母、数字和下划线，"
                "且不能以 @ 符号开头"
            )

        return normalized


class FollowResponse(UTCDatetimeModel):
    """关注响应模型。

    返回用户关注的 Twitter 账号信息。
    """

    id: int = Field(..., description="关注记录 ID")
    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="Twitter 用户名")
    created_at: datetime = Field(..., description="创建时间")


# ==================== 管理员 API 模型 ====================


class CreateScraperFollowRequest(BaseModel):
    """创建抓取账号请求模型。

    管理员用于添加平台级抓取账号。
    """

    username: str = Field(
        ...,
        min_length=1,
        max_length=15,
        description="Twitter 用户名",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="添加理由",
    )
    added_by: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="添加人标识",
    )

    @field_validator("username")
    @classmethod
    def validate_and_normalize_username(cls, v: str) -> str:
        """验证并标准化 Twitter 用户名。

        Args:
            v: 用户名

        Returns:
            标准化后的用户名

        Raises:
            ValueError: 如果用户名格式无效
        """
        normalized = _normalize_username(v)
        if not normalized:
            raise ValueError("用户名不能为空")

        if len(normalized) > 15:
            raise ValueError("用户名不能超过 15 个字符")

        if not normalized.replace("_", "").isalnum():
            raise ValueError(
                "用户名只能包含字母、数字和下划线"
            )

        return normalized


class ScraperFollowResponse(UTCDatetimeModel):
    """抓取账号响应模型。

    返回平台级抓取账号信息。
    """

    id: int = Field(..., description="抓取账号 ID")
    username: str = Field(..., description="Twitter 用户名")
    added_at: datetime = Field(..., description="添加时间")
    reason: str = Field(..., description="添加理由")
    added_by: str = Field(..., description="添加人")
    is_active: bool = Field(..., description="是否启用")


class UpdateScraperFollowRequest(BaseModel):
    """更新抓取账号请求模型。

    管理员用于更新抓取账号配置。
    """

    reason: str | None = Field(
        None,
        min_length=1,
        max_length=500,
        description="新的添加理由",
    )
    is_active: bool | None = Field(
        None,
        description="是否启用",
    )


# ==================== 调度配置管理 API 模型 ====================


class UpdateScheduleIntervalRequest(BaseModel):
    """更新抓取间隔请求模型。"""

    interval_seconds: int = Field(
        ..., ge=300, le=604800,
        description="抓取间隔（秒），300-604800",
    )


class UpdateScheduleNextRunRequest(BaseModel):
    """更新下次触发时间请求模型。"""

    next_run_time: datetime = Field(
        ..., description="下次触发时间（ISO 8601，必须为未来时间）",
    )


class ScheduleConfigResponse(UTCDatetimeModel):
    """调度配置响应模型。"""

    interval_seconds: int = Field(..., description="当前抓取间隔（秒）")
    next_run_time: datetime | None = Field(None, description="下次触发时间")
    scheduler_running: bool = Field(..., description="调度器是否运行中")
    job_active: bool = Field(False, description="调度任务是否活跃")
    is_enabled: bool = Field(False, description="调度是否已启用")
    updated_at: datetime | None = Field(None, description="最后配置更新时间")
    updated_by: str | None = Field(None, description="最后更新人")
    message: str | None = Field(None, description="附加信息（如调度器未运行提示）")


# ==================== 通用响应模型 ====================


class DeleteResponse(BaseModel):
    """删除操作响应模型。

    成功删除操作的统一响应格式。
    """

    message: str = Field(..., description="操作结果消息")


class ErrorResponse(BaseModel):
    """错误响应模型。

    统一的错误响应格式。
    """

    detail: str = Field(..., description="错误详情")
    error_code: str | None = Field(None, description="错误代码")
