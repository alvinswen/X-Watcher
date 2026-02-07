"""去重领域模型。

定义去重相关的 Pydantic 数据模型。
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DeduplicationType(str, Enum):
    """去重类型枚举。

    表示去重组的类型。
    """

    exact_duplicate = "exact_duplicate"
    similar_content = "similar_content"


class DuplicateGroup(BaseModel):
    """精确重复组模型。

    表示一组完全相同或存在转发关系的推文。
    """

    representative_id: str = Field(..., description="代表推文 ID（最早创建）")
    tweet_ids: list[str] = Field(..., description="组内所有推文 ID")
    created_at: datetime = Field(..., description="最早推文的创建时间")


class SimilarGroup(BaseModel):
    """相似内容组模型。

    表示一组内容相似的推文。
    """

    representative_id: str = Field(..., description="代表推文 ID")
    tweet_ids: list[str] = Field(..., description="组内所有推文 ID")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="平均相似度分数")


class DeduplicationGroup(BaseModel):
    """去重组聚合模型。

    表示一个完整的去重组，可持久化到数据库。
    """

    group_id: str = Field(..., description="去重组唯一 ID")
    representative_tweet_id: str = Field(..., description="代表推文 ID")
    deduplication_type: DeduplicationType = Field(..., description="去重类型")
    similarity_score: float | None = Field(None, ge=0.0, le=1.0, description="相似度分数")
    tweet_ids: list[str] = Field(..., description="组内所有推文 ID")
    created_at: datetime = Field(..., description="去重组创建时间")

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class DeduplicationResult(BaseModel):
    """去重结果模型。

    表示去重操作的统计结果。
    """

    total_tweets: int = Field(..., ge=0, description="处理的总推文数")
    exact_duplicate_count: int = Field(..., ge=0, description="精确重复组数")
    similar_content_count: int = Field(..., ge=0, description="相似内容组数")
    affected_tweets: int = Field(..., ge=0, description="被去重的推文数")
    preserved_tweets: int = Field(..., ge=0, description="保留的推文数")
    elapsed_seconds: float = Field(..., ge=0.0, description="处理耗时（秒）")


class DeduplicationConfig(BaseModel):
    """去重策略配置模型。

    定义可配置的去重参数。
    """

    similarity_threshold: float = Field(
        default=0.85, ge=0.0, le=1.0, description="相似度阈值"
    )
    enable_exact_duplicate: bool = Field(
        default=True, description="是否启用精确重复检测"
    )
    enable_similar_content: bool = Field(
        default=True, description="是否启用相似内容检测"
    )
    deduplication_method: Literal["auto", "manual", "hybrid"] = Field(
        default="auto", description="去重触发方式"
    )
    use_embedding_model: bool = Field(
        default=False, description="是否使用嵌入模型（预留）"
    )
    embedding_model: str | None = Field(
        default=None, description="嵌入模型名称（预留）"
    )
    batch_size: int = Field(
        default=1000, ge=1, le=10000, description="分批处理大小"
    )
    time_window_days: int = Field(
        default=7, ge=1, le=30, description="增量去重时间窗口（天）"
    )

    @field_validator("similarity_threshold")
    @classmethod
    def validate_similarity_threshold(cls, v: float) -> float:
        """验证相似度阈值。"""
        if not 0.0 <= v <= 1.0:
            raise ValueError("similarity_threshold 必须在 0-1 之间")
        return v

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """验证分批大小。"""
        if not 1 <= v <= 10000:
            raise ValueError("batch_size 必须在 1-10000 之间")
        return v
