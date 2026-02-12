"""推文数据库 ORM 模型。

定义 Tweet 和 DeduplicationGroup 的 SQLAlchemy 异步 ORM 模型。
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models import Base


class DeduplicationType(str, Enum):
    """去重类型枚举。

    表示去重组的类型。
    """

    exact_duplicate = "exact_duplicate"
    similar_content = "similar_content"


class TweetOrm(Base):
    """推文 ORM 模型。

    对应 tweets 表，存储从 X 平台抓取的推文数据。
    """

    __tablename__ = "tweets"

    # 主键和必需字段
    tweet_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, comment="推文唯一 ID"
    )
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="推文内容")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="推文创建时间",
    )
    author_username: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="作者用户名"
    )

    # 可选字段
    author_display_name: Mapped[str | None] = mapped_column(
        String(255), comment="作者显示名称"
    )
    referenced_tweet_id: Mapped[str | None] = mapped_column(
        String(255), comment="引用的推文 ID（外部引用，不设 FK 约束）"
    )
    reference_type: Mapped[str | None] = mapped_column(
        String(20), comment="引用类型：retweeted, quoted, replied_to"
    )
    media: Mapped[dict | None] = mapped_column(JSON, comment="媒体附件 JSON 数据")
    referenced_tweet_text: Mapped[str | None] = mapped_column(
        Text, comment="被引用/转发推文的完整文本"
    )
    referenced_tweet_media: Mapped[dict | None] = mapped_column(
        JSON, comment="被引用/转发推文的媒体附件 JSON"
    )
    deduplication_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("deduplication_groups.group_id", ondelete="SET NULL"),
        comment="关联的去重组 ID",
    )

    # 时间戳字段
    db_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="数据库记录创建时间",
    )
    db_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="数据库记录更新时间",
    )

    # 关系
    deduplication_group: Mapped["DeduplicationGroupOrm"] = relationship(
        "DeduplicationGroupOrm",
        backref="tweets",
        foreign_keys=[deduplication_group_id],
        remote_side="[DeduplicationGroupOrm.group_id]",
    )

    # 表选项
    __table_args__ = (
        {"comment": "推文数据表"},
    )

    def to_domain(self) -> "src.scraper.domain.models.Tweet":
        """转换为领域模型。

        Returns:
            Tweet: 领域模型实例
        """
        from src.scraper.domain.models import Media, ReferenceType, Tweet

        media_list = None
        if self.media:
            media_list = [Media(**m) for m in self.media]

        referenced_tweet_media_list = None
        if self.referenced_tweet_media:
            referenced_tweet_media_list = [Media(**m) for m in self.referenced_tweet_media]

        reference_type_enum = None
        if self.reference_type:
            reference_type_enum = ReferenceType(self.reference_type)

        # 处理时区：如果 created_at 没有时区信息，假设是 UTC
        created_at = self.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        return Tweet(
            tweet_id=self.tweet_id,
            text=self.text,
            created_at=created_at,
            author_username=self.author_username,
            author_display_name=self.author_display_name,
            referenced_tweet_id=self.referenced_tweet_id,
            reference_type=reference_type_enum,
            media=media_list,
            referenced_tweet_text=self.referenced_tweet_text,
            referenced_tweet_media=referenced_tweet_media_list,
        )

    @classmethod
    def from_domain(cls, tweet: "src.scraper.domain.models.Tweet") -> "TweetOrm":
        """从领域模型创建 ORM 实例。

        Args:
            tweet: 领域模型实例

        Returns:
            TweetOrm: ORM 实例
        """
        media_dict = None
        if tweet.media:
            media_dict = [m.model_dump(mode="json", exclude_none=True) for m in tweet.media]

        referenced_tweet_media_dict = None
        if tweet.referenced_tweet_media:
            referenced_tweet_media_dict = [
                m.model_dump(mode="json", exclude_none=True)
                for m in tweet.referenced_tweet_media
            ]

        return cls(
            tweet_id=tweet.tweet_id,
            text=tweet.text,
            created_at=tweet.created_at,
            author_username=tweet.author_username,
            author_display_name=tweet.author_display_name,
            referenced_tweet_id=tweet.referenced_tweet_id,
            reference_type=tweet.reference_type.value if tweet.reference_type else None,
            media=media_dict,
            referenced_tweet_text=tweet.referenced_tweet_text,
            referenced_tweet_media=referenced_tweet_media_dict,
        )


class DeduplicationGroupOrm(Base):
    """去重组 ORM 模型。

    对应 deduplication_groups 表，存储推文去重结果。
    """

    __tablename__ = "deduplication_groups"

    # 主键
    group_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, comment="去重组唯一 ID"
    )

    # 代表推文 ID（组内最早创建的推文）
    representative_tweet_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("tweets.tweet_id", ondelete="CASCADE"),
        nullable=False,
        comment="代表推文 ID",
    )

    # 去重类型
    deduplication_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="去重类型：exact_duplicate, similar_content",
    )

    # 相似度分数（仅相似内容去重时有值）
    similarity_score: Mapped[float | None] = mapped_column(
        Float, comment="平均相似度分数（0-1）"
    )

    # 组内所有推文 ID 列表
    tweet_ids: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="组内所有推文 ID 列表"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="去重组创建时间",
    )

    # 关系
    representative: Mapped["TweetOrm"] = relationship(
        "TweetOrm",
        backref="represented_groups",
        foreign_keys=[representative_tweet_id],
        remote_side="[TweetOrm.tweet_id]",
    )

    # 表选项和索引
    __table_args__ = (
        {"comment": "去重组数据表"},
    )

    def to_domain(self) -> "src.deduplication.domain.models.DeduplicationGroup":
        """转换为领域模型。

        Returns:
            DeduplicationGroup: 领域模型实例
        """
        from src.deduplication.domain.models import DeduplicationGroup, DeduplicationType

        return DeduplicationGroup(
            group_id=self.group_id,
            representative_tweet_id=self.representative_tweet_id,
            deduplication_type=DeduplicationType(self.deduplication_type),
            similarity_score=self.similarity_score,
            tweet_ids=self.tweet_ids,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(
        cls, group: "src.deduplication.domain.models.DeduplicationGroup"
    ) -> "DeduplicationGroupOrm":
        """从领域模型创建 ORM 实例。

        Args:
            group: 领域模型实例

        Returns:
            DeduplicationGroupOrm: ORM 实例
        """
        return cls(
            group_id=group.group_id,
            representative_tweet_id=group.representative_tweet_id,
            deduplication_type=group.deduplication_type.value,
            similarity_score=group.similarity_score,
            tweet_ids=group.tweet_ids,
            created_at=group.created_at,
        )
