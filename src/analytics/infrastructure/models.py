"""聚类分析 ORM 模型。"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models import Base
from src.analytics.domain.models import ClusterAssignmentDomain, ClusteringRunDomain, ClusteringRunStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ClusteringRunOrm(Base):
    """聚类运行记录表。"""
    __tablename__ = "clustering_runs"
    __table_args__ = (
        Index("ix_clustering_runs_status", "status"),
        Index("ix_clustering_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ClusteringRunStatus.pending.value
    )
    cut_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_clusters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_accounts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_excluded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_tweets_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    linkage_method: Mapped[str] = mapped_column(String(20), nullable=False, default="average")
    linkage_matrix_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_labels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignments: Mapped[list["ClusterAssignmentOrm"]] = relationship(
        "ClusterAssignmentOrm",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_domain(self) -> ClusteringRunDomain:
        return ClusteringRunDomain(
            id=self.id,
            status=ClusteringRunStatus(self.status),
            cut_height=self.cut_height,
            num_clusters=self.num_clusters,
            num_accounts=self.num_accounts,
            num_excluded=self.num_excluded,
            min_tweets_threshold=self.min_tweets_threshold,
            linkage_method=self.linkage_method,
            linkage_matrix_json=self.linkage_matrix_json,
            account_labels_json=self.account_labels_json,
            error_message=self.error_message,
            created_at=self.created_at,
            completed_at=self.completed_at,
        )


class ClusterAssignmentOrm(Base):
    """账号聚类分配表。"""
    __tablename__ = "cluster_assignments"
    __table_args__ = (
        UniqueConstraint("run_id", "username", name="uq_cluster_assignments_run_username"),
        Index("ix_cluster_assignments_run_id", "run_id"),
        Index("ix_cluster_assignments_cluster_id", "cluster_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clustering_runs.id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hourly_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)
    tweet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    run: Mapped["ClusteringRunOrm"] = relationship("ClusteringRunOrm", back_populates="assignments")

    def to_domain(self) -> ClusterAssignmentDomain:
        return ClusterAssignmentDomain(
            id=self.id,
            run_id=self.run_id,
            username=self.username,
            cluster_id=self.cluster_id,
            hourly_distribution_json=self.hourly_distribution_json,
            tweet_count=self.tweet_count,
            is_manual_override=self.is_manual_override,
        )
