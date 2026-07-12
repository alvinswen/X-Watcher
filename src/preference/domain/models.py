"""关注列表管理领域模型。

定义关注列表管理相关的 Pydantic 领域模型，与 ORM 模型分离。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
    brief_intro: str | None = Field(None, description="极简介绍（≤10汉字）")
    backfill_status: str = Field(
        "pending", description="回溯状态: pending/running/completed/skipped"
    )
    backfill_completed_at: datetime | None = Field(None, description="回溯完成时间")

    @classmethod
    def from_orm(cls, orm_obj: Any) -> "ScraperFollow":
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
            brief_intro=orm_obj.brief_intro,
            backfill_status=orm_obj.backfill_status or "pending",
            backfill_completed_at=orm_obj.backfill_completed_at,
        )


class XUserProfile(BaseModel):
    """X 平台用户档案领域模型。

    缓存从 TwitterAPI.io 获取的用户档案信息。
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
    fetched_at: datetime | None = Field(None, description="数据获取时间")

    @classmethod
    def from_orm(cls, orm_obj: Any) -> XUserProfile:
        """从 ORM 模型转换为领域模型。"""
        return cls(
            platform_user_id=orm_obj.platform_user_id,
            username=orm_obj.username,
            display_name=orm_obj.display_name,
            is_blue_verified=orm_obj.is_blue_verified,
            verified_type=orm_obj.verified_type,
            profile_picture=orm_obj.profile_picture,
            cover_picture=orm_obj.cover_picture,
            description=orm_obj.description,
            location=orm_obj.location,
            followers_count=orm_obj.followers_count,
            following_count=orm_obj.following_count,
            statuses_count=orm_obj.statuses_count,
            favourites_count=orm_obj.favourites_count,
            media_count=orm_obj.media_count,
            account_created_at=orm_obj.account_created_at,
            is_automated=orm_obj.is_automated,
            possibly_sensitive=orm_obj.possibly_sensitive,
            pinned_tweet_ids=orm_obj.pinned_tweet_ids,
            unavailable=orm_obj.unavailable,
            unavailable_reason=orm_obj.unavailable_reason,
            fetched_at=orm_obj.fetched_at,
        )

    @classmethod
    def from_api_response(cls, data: dict[str, Any], fetched_at: datetime) -> XUserProfile:
        """从 TwitterAPI.io 用户信息响应转换为领域模型。

        处理 camelCase → snake_case 字段映射。

        Args:
            data: TwitterAPI.io 返回的用户信息字典
            fetched_at: 数据获取时间

        Returns:
            XUserProfile 领域模型实例
        """
        return cls(
            platform_user_id=str(data.get("id", "")),
            username=data.get("userName", ""),
            display_name=data.get("name"),
            is_blue_verified=data.get("isBlueVerified", False),
            verified_type=data.get("verifiedType"),
            profile_picture=data.get("profilePicture"),
            cover_picture=data.get("coverPicture"),
            description=data.get("description"),
            location=data.get("location"),
            followers_count=data.get("followers"),
            following_count=data.get("following"),
            statuses_count=data.get("statusesCount"),
            favourites_count=data.get("favouritesCount"),
            media_count=data.get("mediaCount"),
            account_created_at=data.get("createdAt"),
            is_automated=data.get("isAutomated", False),
            possibly_sensitive=data.get("possiblySensitive", False),
            pinned_tweet_ids=data.get("pinnedTweetIds"),
            unavailable=data.get("unavailable", False),
            unavailable_reason=data.get("unavailableReason"),
            fetched_at=fetched_at,
        )

    def to_raw_json(self, data: dict[str, Any]) -> str:
        """将原始 API 响应序列化为 JSON 字符串。"""
        return json.dumps(data, ensure_ascii=False)
