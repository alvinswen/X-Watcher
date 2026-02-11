"""数据库模型模块。

定义 SQLAlchemy ORM 模型。
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    UniqueConstraint,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""

    pass


# 延迟初始化引擎
_engine = None


def get_engine():
    """获取数据库引擎。

    用于同步数据库操作。引擎在首次调用时创建。
    """
    global _engine
    if _engine is None:
        from src.config import get_settings

        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=settings.log_level == "DEBUG",
        )
    return _engine


# 向后兼容的属性
def engine():
    """获取数据库引擎单例（向后兼容）。"""
    return get_engine()


class User(Base):
    """用户模型。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # 关系
    preferences: Mapped[list["Preference"]] = relationship(
        "Preference", back_populates="user", cascade="all, delete-orphan"
    )
    news_items: Mapped[list["NewsItem"]] = relationship(
        "NewsItem", back_populates="user", cascade="all, delete-orphan"
    )
    twitter_follows: Mapped[list["TwitterFollow"]] = relationship(
        "TwitterFollow", back_populates="user", cascade="all, delete-orphan"
    )
    filter_rules: Mapped[list["FilterRule"]] = relationship(
        "FilterRule", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    """API Key 模型。"""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    # 索引
    __table_args__ = (
        Index("idx_api_keys_key_hash", "key_hash"),
        Index("idx_api_keys_user_id", "user_id"),
    )


class Preference(Base):
    """用户偏好模型。"""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="preferences")


class NewsItem(Base):
    """新闻项模型。"""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="news_items")


class ScraperFollow(Base):
    """平台抓取账号列表模型。

    管理员维护的平台级 Twitter 关注列表，用户关注列表从中初始化。
    """

    __tablename__ = "scraper_follows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(15), nullable=False, unique=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    added_by: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 索引
    __table_args__ = (
        Index("idx_scraper_follows_username", "username"),
        Index("idx_scraper_follows_active", "is_active"),
    )


class TwitterFollow(Base):
    """用户关注列表模型。

    用户从平台抓取列表中选择的 Twitter 关注账号。
    """

    __tablename__ = "twitter_follows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(15), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, onupdate=lambda: datetime.now(timezone.utc)
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="twitter_follows")

    # 约束和索引
    __table_args__ = (
        UniqueConstraint("user_id", "username", name="uq_twitter_follows_user_username"),
        CheckConstraint("priority BETWEEN 1 AND 10", name="ck_twitter_follows_priority_range"),
        Index("idx_twitter_follows_user_id", "user_id"),
        Index("idx_twitter_follows_username", "username"),
        Index("idx_twitter_follows_priority", "priority"),
    )


class FilterRule(Base):
    """过滤规则模型。

    用户配置的内容过滤规则（关键词、话题标签、内容类型）。
    """

    __tablename__ = "filter_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filter_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="filter_rules")

    # 约束和索引
    __table_args__ = (
        CheckConstraint(
            "filter_type IN ('keyword', 'hashtag', 'content_type')",
            name="ck_filter_rules_type"
        ),
        Index("idx_filter_rules_user_id", "user_id"),
        Index("idx_filter_rules_type", "filter_type"),
    )
