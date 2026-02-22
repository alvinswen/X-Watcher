"""X 平台用户档案 ORM 模型。

缓存从 TwitterAPI.io 获取的用户档案数据。
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models import Base


class XUserProfileOrm(Base):
    """X 平台用户档案 ORM 模型。

    以 platform_user_id 为主键，存储从 TwitterAPI.io 获取的完整用户档案。
    """

    __tablename__ = "x_user_profiles"

    platform_user_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="X 平台永久 user_id"
    )
    username: Mapped[str] = mapped_column(
        String(15), nullable=False, comment="当前用户名（可变）"
    )
    display_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="显示名称"
    )
    is_blue_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否蓝标认证"
    )
    verified_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="认证类型"
    )
    profile_picture: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="头像 URL"
    )
    cover_picture: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="封面图 URL"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="个人简介"
    )
    location: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="位置"
    )
    followers_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="粉丝数"
    )
    following_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="关注数"
    )
    statuses_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="推文总数"
    )
    favourites_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="点赞数"
    )
    media_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="媒体推文数"
    )
    account_created_at: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="账号创建日期（原始字符串）"
    )
    is_automated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否自动化账号"
    )
    possibly_sensitive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否可能包含敏感内容"
    )
    pinned_tweet_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="置顶推文 ID 列表"
    )
    unavailable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="账号是否不可用"
    )
    unavailable_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="不可用原因"
    )
    raw_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="完整 API 响应 JSON"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="数据获取时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="记录创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="记录更新时间",
    )

    __table_args__ = (
        Index("idx_x_user_profiles_username", "username"),
        Index("idx_x_user_profiles_fetched_at", "fetched_at"),
    )
