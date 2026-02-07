"""摘要数据库 ORM 模型。

定义 SummaryOrm 的 SQLAlchemy 异步 ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models import Base


class SummaryOrm(Base):
    """摘要 ORM 模型。

    对应 summaries 表，存储推文的摘要和翻译结果。
    """

    __tablename__ = "summaries"

    # 主键
    summary_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, comment="摘要唯一标识（UUID）"
    )

    # 外键关联推文
    tweet_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("tweets.tweet_id", ondelete="CASCADE"),
        nullable=False,
        comment="关联的推文 ID",
    )

    # 摘要和翻译内容
    summary_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="中文摘要内容"
    )
    translation_text: Mapped[str | None] = mapped_column(
        Text, comment="中文翻译内容"
    )

    # 模型信息
    model_provider: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="模型提供商（openrouter, minimax, open_source）"
    )
    model_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="模型名称"
    )

    # Token 统计
    prompt_tokens: Mapped[int] = mapped_column(
        nullable=False, comment="输入 token 数"
    )
    completion_tokens: Mapped[int] = mapped_column(
        nullable=False, comment="输出 token 数"
    )
    total_tokens: Mapped[int] = mapped_column(
        nullable=False, comment="总 token 数"
    )

    # 成本
    cost_usd: Mapped[float] = mapped_column(
        Float, nullable=False, comment="成本（美元）"
    )

    # 缓存相关
    cached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否来自缓存"
    )
    is_generated_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否为生成的摘要（False表示原文太短直接返回）"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="内容哈希（缓存键）"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="更新时间",
    )

    # 表选项
    __table_args__ = (
        {"comment": "摘要记录表"},
    )

    def to_domain(self) -> "src.summarization.domain.models.SummaryRecord":
        """转换为领域模型。

        Returns:
            SummaryRecord: 领域模型实例
        """
        from src.summarization.domain.models import SummaryRecord

        return SummaryRecord(
            summary_id=self.summary_id,
            tweet_id=self.tweet_id,
            summary_text=self.summary_text,
            translation_text=self.translation_text,
            model_provider=self.model_provider,
            model_name=self.model_name,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            cost_usd=self.cost_usd,
            cached=self.cached,
            is_generated_summary=self.is_generated_summary,
            content_hash=self.content_hash,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(
        cls, record: "src.summarization.domain.models.SummaryRecord"
    ) -> "SummaryOrm":
        """从领域模型创建 ORM 实例。

        Args:
            record: 领域模型实例

        Returns:
            SummaryOrm: ORM 实例
        """
        return cls(
            summary_id=record.summary_id,
            tweet_id=record.tweet_id,
            summary_text=record.summary_text,
            translation_text=record.translation_text,
            model_provider=record.model_provider,
            model_name=record.model_name,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            total_tokens=record.total_tokens,
            cost_usd=record.cost_usd,
            cached=record.cached,
            is_generated_summary=record.is_generated_summary,
            content_hash=record.content_hash,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
