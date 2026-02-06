"""推文数据库 ORM 模型。

定义 Tweet 的 SQLAlchemy 异步 ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models import Base


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
        String(255), ForeignKey("tweets.tweet_id", ondelete="SET NULL"), comment="引用的推文 ID"
    )
    reference_type: Mapped[str | None] = mapped_column(
        String(20), comment="引用类型：retweeted, quoted, replied_to"
    )
    media: Mapped[dict | None] = mapped_column(JSON, comment="媒体附件 JSON 数据")

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
    referenced_by: Mapped[list["TweetOrm"]] = relationship(
        "TweetOrm",
        backref="references",
        foreign_keys=[referenced_tweet_id],
        remote_side="[TweetOrm.tweet_id]",
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

        reference_type_enum = None
        if self.reference_type:
            reference_type_enum = ReferenceType(self.reference_type)

        return Tweet(
            tweet_id=self.tweet_id,
            text=self.text,
            created_at=self.created_at,
            author_username=self.author_username,
            author_display_name=self.author_display_name,
            referenced_tweet_id=self.referenced_tweet_id,
            reference_type=reference_type_enum,
            media=media_list,
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

        return cls(
            tweet_id=tweet.tweet_id,
            text=tweet.text,
            created_at=tweet.created_at,
            author_username=tweet.author_username,
            author_display_name=tweet.author_display_name,
            referenced_tweet_id=tweet.referenced_tweet_id,
            reference_type=tweet.reference_type.value if tweet.reference_type else None,
            media=media_dict,
        )
