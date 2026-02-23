"""聚类分析 API 请求和响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import UTCDatetimeModel


# ── 请求模型 ──

class RunClusteringRequest(BaseModel):
    min_tweets: int = Field(default=20, ge=1, description="最小推文数阈值")
    linkage_method: str = Field(default="average", description="链接方法")
    cut_height: float | None = Field(default=None, ge=0, description="树状图切割高度")
    num_clusters: int | None = Field(default=None, ge=2, description="聚类组数")


class ReCutRequest(BaseModel):
    cut_height: float | None = Field(default=None, ge=0, description="树状图切割高度")
    num_clusters: int | None = Field(default=None, ge=2, description="聚类组数")


class MoveAccountRequest(BaseModel):
    cluster_id: int = Field(..., ge=0, description="目标聚类组 ID")


# ── 响应模型 ──

class AccountDistributionResponse(BaseModel):
    username: str
    distribution: list[float]
    tweet_count: int


class DistributionsResponse(BaseModel):
    distributions: list[AccountDistributionResponse]
    excluded: list[str]


class ClusterAssignmentResponse(BaseModel):
    id: int
    username: str
    cluster_id: int
    hourly_distribution: list[float]
    tweet_count: int
    is_manual_override: bool


class ClusteringRunSummaryResponse(UTCDatetimeModel):
    id: int
    status: str
    num_clusters: int | None
    num_accounts: int | None
    num_excluded: int | None
    min_tweets_threshold: int
    linkage_method: str
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class ClusteringRunDetailResponse(ClusteringRunSummaryResponse):
    cut_height: float | None
    linkage_matrix: list[list[float]] | None
    account_labels: list[str] | None
    assignments: list[ClusterAssignmentResponse]


# ── 发文频次分析模型 ──


class TimeRangeResponse(BaseModel):
    """时间范围响应。"""

    start: str
    end: str


class FrequencySlotResponse(BaseModel):
    """单个时段发文计数。"""

    slot: str
    count: int


class PostingFrequencyResponse(BaseModel):
    """发文频次分析响应。"""

    topic_id: int
    topic_name: str
    slot_minutes: int
    slots: int
    tz_offset: int
    time_range: TimeRangeResponse
    distribution: list[FrequencySlotResponse]
    total_tweets: int
