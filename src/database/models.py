"""数据库模型模块。

定义 SQLAlchemy ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.config import get_settings

# 获取配置
settings = get_settings()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",  # DEBUG 模式下打印 SQL
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""

    pass


class User(Base):
    """用户模型。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
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
