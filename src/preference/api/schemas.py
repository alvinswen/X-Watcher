"""偏好管理 API 请求/响应模型。

定义 FastAPI 端点使用的 Pydantic 模型。
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
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="优先级（1-10，默认 5）",
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


class FollowResponse(BaseModel):
    """关注响应模型。

    返回用户关注的 Twitter 账号信息。
    """

    id: int = Field(..., description="关注记录 ID")
    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="Twitter 用户名")
    priority: int = Field(..., ge=1, le=10, description="优先级")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class UpdatePriorityRequest(BaseModel):
    """更新优先级请求模型。

    用于修改已关注账号的优先级。
    """

    priority: int = Field(
        ...,
        ge=1,
        le=10,
        description="新的优先级（1-10）",
    )


class CreateFilterRequest(BaseModel):
    """创建过滤规则请求模型。

    用于添加内容过滤规则。
    """

    filter_type: FilterType = Field(
        ...,
        description="过滤类型",
    )
    value: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="过滤值（关键词/话题标签/内容类型）",
    )


class FilterResponse(BaseModel):
    """过滤规则响应模型。

    返回用户配置的过滤规则信息。
    """

    id: str = Field(..., description="过滤规则 ID（UUID）")
    user_id: int = Field(..., description="用户 ID")
    filter_type: FilterType = Field(..., description="过滤类型")
    value: str = Field(..., description="过滤值")
    created_at: datetime = Field(..., description="创建时间")


class UpdateSortingRequest(BaseModel):
    """更新排序偏好请求模型。

    用于修改新闻流排序方式。
    """

    sort_type: SortType = Field(
        ...,
        description="排序类型",
    )


class SortingPreferenceResponse(BaseModel):
    """排序偏好响应模型。

    返回当前的排序偏好设置。
    """

    sort_type: SortType = Field(..., description="当前排序类型")


class PreferenceResponse(BaseModel):
    """偏好配置响应模型。

    返回用户的所有偏好配置。
    """

    user_id: int = Field(..., description="用户 ID")
    sorting: SortingPreferenceResponse = Field(
        ..., description="排序偏好"
    )
    follows: list[FollowResponse] = Field(
        default_factory=list,
        description="关注列表",
    )
    filters: list[FilterResponse] = Field(
        default_factory=list,
        description="过滤规则列表",
    )


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


class ScraperFollowResponse(BaseModel):
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


# ==================== 新闻流响应模型 ====================


class TweetWithRelevance(BaseModel):
    """带相关性分数的推文响应模型。

    用于个性化新闻流 API 返回。
    """

    tweet: dict = Field(
        ...,
        description="推文数据（包含 id、text、author、created_at 等）",
    )
    relevance_score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="相关性分数（0.0-1.0，仅当 sort=relevance 时有值）",
    )


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
