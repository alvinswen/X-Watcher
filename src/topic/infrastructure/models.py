"""主题管理 ORM 模型。"""

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models import Base
from src.topic.domain.models import (
    TopicAccountDomain,
    TopicDomain,
    TopicSummaryDomain,
    TopicSummaryTaskDomain,
    TopicSummaryTaskStatus,
    TopicWithCountDomain,
    TopicDetailDomain,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TopicOrm(Base):
    """主题表 ORM 模型。"""
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_topics_user_id_name"),
        Index("ix_topics_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now, onupdate=_utc_now)

    # Relationships
    accounts: Mapped[list["TopicAccountOrm"]] = relationship(
        "TopicAccountOrm", back_populates="topic", cascade="all, delete-orphan", lazy="selectin"
    )
    summary_tasks: Mapped[list["TopicSummaryTaskOrm"]] = relationship(
        "TopicSummaryTaskOrm", back_populates="topic", cascade="all, delete-orphan", lazy="noload"
    )

    def to_domain(self) -> TopicDomain:
        return TopicDomain(
            id=self.id,
            name=self.name,
            description=self.description,
            user_id=self.user_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_domain_with_count(self, account_count: int) -> TopicWithCountDomain:
        return TopicWithCountDomain(
            id=self.id,
            name=self.name,
            description=self.description,
            user_id=self.user_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            account_count=account_count,
        )

    def to_detail_domain(self) -> TopicDetailDomain:
        return TopicDetailDomain(
            id=self.id,
            name=self.name,
            description=self.description,
            user_id=self.user_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            accounts=[a.to_domain() for a in self.accounts],
        )

    @classmethod
    def from_domain(cls, name: str, description: str | None = None, user_id: int | None = None) -> "TopicOrm":
        return cls(name=name, description=description, user_id=user_id)


class TopicAccountOrm(Base):
    """主题账号关联表 ORM 模型。"""
    __tablename__ = "topic_accounts"
    __table_args__ = (
        UniqueConstraint("topic_id", "username", name="uq_topic_accounts_topic_username"),
        Index("ix_topic_accounts_topic_id", "topic_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)

    # Relationships
    topic: Mapped["TopicOrm"] = relationship("TopicOrm", back_populates="accounts")

    def to_domain(self) -> TopicAccountDomain:
        return TopicAccountDomain(
            id=self.id,
            topic_id=self.topic_id,
            username=self.username,
            added_at=self.added_at,
        )


class TopicSummaryTaskOrm(Base):
    """摘要任务表 ORM 模型。"""
    __tablename__ = "topic_summary_tasks"
    __table_args__ = (
        Index("ix_topic_summary_tasks_topic_id", "topic_id"),
        Index("ix_topic_summary_tasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    time_span_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    tz_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="用户时区偏移（分钟），来自 JS getTimezoneOffset()")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TopicSummaryTaskStatus.pending.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    topic: Mapped["TopicOrm"] = relationship("TopicOrm", back_populates="summary_tasks")
    summary: Mapped["TopicSummaryOrm | None"] = relationship(
        "TopicSummaryOrm", back_populates="task", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )

    def to_domain(self) -> TopicSummaryTaskDomain:
        return TopicSummaryTaskDomain(
            id=self.id,
            topic_id=self.topic_id,
            topic_name=self.topic.name,
            time_span_hours=self.time_span_hours,
            deadline=self.deadline,
            custom_prompt=self.custom_prompt,
            status=TopicSummaryTaskStatus(self.status),
            error_message=self.error_message,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            summary=self.summary.to_domain() if self.summary else None,
        )


class TopicSummaryOrm(Base):
    """摘要结果表 ORM 模型。"""
    __tablename__ = "topic_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topic_summary_tasks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tweet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    account_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    # 结构化扩展字段：observations / review_window / review_kind 等机器可读信息。
    # 列名 metadata_json 而非 metadata：避免与 SQLAlchemy Base.metadata 保留属性冲突。
    metadata_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'"),
    )

    # Relationships
    task: Mapped["TopicSummaryTaskOrm"] = relationship("TopicSummaryTaskOrm", back_populates="summary")

    def to_domain(self) -> TopicSummaryDomain:
        return TopicSummaryDomain(
            id=self.id,
            task_id=self.task_id,
            content=self.content,
            llm_provider=self.llm_provider,
            llm_model=self.llm_model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            cost_usd=self.cost_usd,
            tweet_count=self.tweet_count,
            account_count=self.account_count,
            created_at=self.created_at,
            metadata_json=self.metadata_json or {},
        )
