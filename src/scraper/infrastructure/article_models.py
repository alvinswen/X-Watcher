"""X Articles ORM 模型。

定义 Article 的 SQLAlchemy ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models import Base


class ArticleOrm(Base):
    """文章 ORM 模型。

    对应 articles 表，存储从 X 平台抓取的长文章内容。
    以 tweet_id 为主键，天然去重和关联。
    """

    __tablename__ = "articles"

    tweet_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, comment="关联推文 ID"
    )
    title: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="文章标题"
    )
    preview_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="预览文本"
    )
    cover_image_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="封面图片 URL"
    )
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="文章正文（纯文本）"
    )
    content_html: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="文章正文（HTML）"
    )
    author_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="作者用户名"
    )
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="数据获取时间"
    )
    db_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="数据库记录创建时间",
    )

    __table_args__ = (
        {"comment": "X 平台长文章数据表"},
    )
