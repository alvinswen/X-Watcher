"""抓取统计 ORM 模型。

定义 scraper_fetch_stats 表的 SQLAlchemy 异步 ORM 模型。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models import Base


class FetchStatsOrm(Base):
    """抓取统计 ORM 模型。

    对应 scraper_fetch_stats 表，记录每个用户的抓取历史统计。
    """

    __tablename__ = "scraper_fetch_stats"

    username: Mapped[str] = mapped_column(
        String(255), primary_key=True, comment="Twitter 用户名"
    )
    last_fetch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="上次抓取时间",
    )
    last_fetched_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="上次 API 返回的推文数"
    )
    last_new_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="上次新增的推文数"
    )
    total_fetches: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="总抓取次数"
    )
    avg_new_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, comment="EMA 平滑的新推文率 (0-1)"
    )
    consecutive_empty_fetches: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="连续 0 新推文次数"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="记录创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(),
        comment="记录更新时间",
    )

    __table_args__ = ({"comment": "抓取统计表"},)

    def to_domain(self) -> "src.scraper.domain.fetch_stats.FetchStats":
        """转换为领域模型。"""
        from src.scraper.domain.fetch_stats import FetchStats

        return FetchStats(
            username=self.username,
            last_fetch_at=self.last_fetch_at,
            last_fetched_count=self.last_fetched_count,
            last_new_count=self.last_new_count,
            total_fetches=self.total_fetches,
            avg_new_rate=self.avg_new_rate,
            consecutive_empty_fetches=self.consecutive_empty_fetches,
        )

    @classmethod
    def from_domain(
        cls, stats: "src.scraper.domain.fetch_stats.FetchStats"
    ) -> "FetchStatsOrm":
        """从领域模型创建 ORM 实例。"""
        from src.scraper.domain.fetch_stats import FetchStats

        return cls(
            username=stats.username,
            last_fetch_at=stats.last_fetch_at,
            last_fetched_count=stats.last_fetched_count,
            last_new_count=stats.last_new_count,
            total_fetches=stats.total_fetches,
            avg_new_rate=stats.avg_new_rate,
            consecutive_empty_fetches=stats.consecutive_empty_fetches,
        )
