"""数据库模型模块。

定义 SQLAlchemy ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    UniqueConstraint,
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
    SQLite 使用 WAL 模式 + busy_timeout；PostgreSQL 使用连接池。
    """
    global _engine
    if _engine is None:
        from src.config import get_settings
        from src.database.dialect import is_sqlite

        settings = get_settings()

        engine_kwargs: dict = {
            "echo": settings.log_level == "DEBUG",
        }

        if is_sqlite():
            engine_kwargs["connect_args"] = {"timeout": 30}
        else:
            engine_kwargs["pool_size"] = 10
            engine_kwargs["max_overflow"] = 20
            engine_kwargs["pool_pre_ping"] = True

        _engine = create_engine(settings.database_url, **engine_kwargs)

        if is_sqlite():
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _engine


def reset_engine() -> None:
    """重置同步数据库引擎单例。

    仅供测试使用，确保测试之间不会共享数据库连接。
    """
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


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
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False
    )

    # 关系
    news_items: Mapped[list["NewsItem"]] = relationship(
        "NewsItem", back_populates="user", cascade="all, delete-orphan"
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
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    # 索引
    __table_args__ = (
        Index("idx_api_keys_key_hash", "key_hash"),
        Index("idx_api_keys_user_id", "user_id"),
    )


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
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False
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
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    added_by: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manual_limit: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    platform_user_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, comment="X 平台永久 user_id"
    )
    brief_intro: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None, comment="极简介绍（≤10汉字）"
    )
    backfill_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="回溯状态: pending/running/completed/skipped",
    )
    backfill_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="回溯完成时间",
    )

    # 索引
    __table_args__ = (
        Index("idx_scraper_follows_username", "username"),
        Index("idx_scraper_follows_active", "is_active"),
        Index("idx_scraper_follows_platform_user_id", "platform_user_id"),
        Index("idx_scraper_follows_backfill_status", "backfill_status"),
    )



class ScraperScheduleConfig(Base):
    """调度配置模型。

    管理员动态调整的抓取调度参数（singleton 单行，id=1）。
    """

    __tablename__ = "scraper_schedule_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=43200
    )
    next_run_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)


class TaskExecutionLog(Base):
    """任务执行日志模型。

    记录手动触发的抓取/摘要/去重等后台任务的执行历史，
    使任务历史在服务重启后仍然可查。
    """

    __tablename__ = "task_execution_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_task_log_task_id", "task_id"),
        Index("idx_task_log_status", "status"),
        Index("idx_task_log_created_at", "created_at"),
    )


