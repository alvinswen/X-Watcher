"""关注列表管理 API 请求/响应模型。

定义 FastAPI 端点使用的 Pydantic 模型。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.preference.domain.models import ScraperFollow, XUserProfile
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

        此处保持宽容语义（剥 @、转小写）；管理抓取接口的严格语义独立保留。
        两者的业务语义归一须另立议题，不在 CHG-037 内选边。

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
            raise ValueError("用户名只能包含字母、数字和下划线")

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

    @classmethod
    def from_domain(cls, follow: ScraperFollow) -> "ScraperFollowResponse":
        """从抓取账号领域模型构造 wire 响应。"""
        return cls(
            id=follow.id,
            username=follow.username,
            platform_user_id=follow.platform_user_id,
            added_at=follow.added_at,
            reason=follow.reason,
            added_by=follow.added_by,
            is_active=follow.is_active,
            manual_limit=follow.manual_limit,
            brief_intro=follow.brief_intro,
        )


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

    @classmethod
    def from_domain(cls, profile: XUserProfile) -> "XUserProfileResponse":
        """从用户档案领域模型构造 wire 响应。"""
        return cls(
            platform_user_id=profile.platform_user_id,
            username=profile.username,
            display_name=profile.display_name,
            is_blue_verified=profile.is_blue_verified,
            verified_type=profile.verified_type,
            profile_picture=profile.profile_picture,
            cover_picture=profile.cover_picture,
            description=profile.description,
            location=profile.location,
            followers_count=profile.followers_count,
            following_count=profile.following_count,
            statuses_count=profile.statuses_count,
            favourites_count=profile.favourites_count,
            media_count=profile.media_count,
            account_created_at=profile.account_created_at,
            is_automated=profile.is_automated,
            possibly_sensitive=profile.possibly_sensitive,
            pinned_tweet_ids=profile.pinned_tweet_ids,
            unavailable=profile.unavailable,
            unavailable_reason=profile.unavailable_reason,
            fetched_at=profile.fetched_at,
        )


class SyncProfilesResponse(BaseModel):
    """档案同步响应模型。"""

    synced: int = Field(..., description="同步的档案数量")
    message: str = Field(..., description="操作结果信息")
