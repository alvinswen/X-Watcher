"""聚类分析领域模型。"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ClusteringRunStatus(str, Enum):
    """聚类运行状态枚举。"""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ClusteringRunDomain(BaseModel):
    """聚类运行领域模型。"""
    id: int
    status: ClusteringRunStatus
    cut_height: float | None = None
    num_clusters: int | None = None
    num_accounts: int | None = None
    num_excluded: int | None = None
    min_tweets_threshold: int
    linkage_method: str
    linkage_matrix_json: str | None = None
    account_labels_json: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ClusterAssignmentDomain(BaseModel):
    """聚类分配领域模型。"""
    id: int
    run_id: int
    username: str
    cluster_id: int
    hourly_distribution_json: str
    tweet_count: int
    is_manual_override: bool


class AccountDistribution(BaseModel):
    """账号 24 小时分布。"""
    username: str
    distribution: list[float]
    tweet_count: int
