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
    platform_user_id: str | None = Field(None, description="X 平台永久 user_id（系统自动获取）")
    added_at: datetime = Field(..., description="添加时间")
    reason: str = Field(..., description="添加理由")
    added_by: str = Field(..., description="添加人")
    is_active: bool = Field(..., description="是否启用")
    manual_limit: int | None = Field(None, description="手动推文数量限制")
    brief_intro: str | None = Field(None, description="极简介绍（≤10汉字）")


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
    manual_limit: int | None = Field(
        default=None,
        ge=0,
        le=1000,
        description="手动推文数量限制（0 表示清除手动设置恢复自动计算，null 表示不修改）",
    )
    brief_intro: str | None = Field(
        default=None,
        max_length=50,
        description="极简介绍（≤10汉字，null 表示不修改，空字符串表示清空）",
    )


# ==================== 抓取分析 API 模型 ====================


class PeriodStats(BaseModel):
    """单个周期的统计数据。"""

    period_start: datetime = Field(..., description="周期开始时间")
    period_end: datetime = Field(..., description="周期结束时间")
    new_tweet_count: int = Field(..., description="该周期内新推文数量")


class FetchAnalysisResponse(UTCDatetimeModel):
    """抓取结果分析响应。"""

    username: str = Field(..., description="Twitter 用户名")
    interval_hours: int = Field(..., description="周期间隔小时数")
    periods: list[PeriodStats] = Field(..., description="各周期统计数据")
    total_new_tweets: int = Field(..., description="总新推文数量")


# ==================== 账号运行时统计模型 ====================


class FollowStatsResponse(BaseModel):
    """账号运行时统计响应。

    包含自动计算的 effective_limit 和近期最大新推文数。
    """

    username: str = Field(..., description="Twitter 用户名")
    effective_limit: int = Field(..., description="自动计算模式下的当前 limit 值")
    max_count_12h: int = Field(..., description="近 14 个 12h 周期的最大新推文数")
    max_count_24h: int = Field(..., description="近 14 个 24h 周期的最大新推文数")


class TweetTimeRangeResponse(BaseModel):
    """账号推文时间范围响应。"""

    username: str = Field(..., description="Twitter 用户名")
    earliest_tweet_at: datetime | None = Field(None, description="系统中最早的推文发布时间")
    latest_tweet_at: datetime | None = Field(None, description="系统中最近的推文发布时间")
    tweet_count: int = Field(0, description="系统中的推文总数")


# ==================== 用户档案 API 模型 ====================


class XUserProfileResponse(UTCDatetimeModel):
    """X 平台用户档案响应模型。

    返回从 TwitterAPI.io 缓存的用户档案信息。
    """

    platform_user_id: str = Field(..., description="X 平台永久 user_id")
    username: str = Field(..., description="当前用户名")
    display_name: str | None = Field(None, description="显示名称")
    is_blue_verified: bool = Field(False, description="蓝标认证")
    verified_type: str | None = Field(None, description="认证类型")
    profile_picture: str | None = Field(None, description="头像 URL")
    cover_picture: str | None = Field(None, description="封面图 URL")
    description: str | None = Field(None, description="个人简介")
    location: str | None = Field(None, description="位置")
    followers_count: int | None = Field(None, description="粉丝数")
    following_count: int | None = Field(None, description="关注数")
    statuses_count: int | None = Field(None, description="推文总数")
    favourites_count: int | None = Field(None, description="点赞数")
    media_count: int | None = Field(None, description="媒体推文数")
    account_created_at: str | None = Field(None, description="账号创建日期")
    is_automated: bool = Field(False, description="是否自动化账号")
    possibly_sensitive: bool = Field(False, description="可能敏感")
    pinned_tweet_ids: list[str] | None = Field(None, description="置顶推文 ID")
    unavailable: bool = Field(False, description="账号不可用")
    unavailable_reason: str | None = Field(None, description="不可用原因")
    fetched_at: datetime = Field(..., description="数据获取时间")


class SyncProfilesResponse(BaseModel):
    """档案同步响应模型。"""

    synced: int = Field(..., description="同步的档案数量")
    message: str = Field(..., description="操作结果信息")


# ==================== 通用响应模型 ====================


class DeleteResponse(BaseModel):
    """删除操作响应模型。

    成功删除操作的统一响应格式。
    """

    message: str = Field(..., description="操作结果消息")
