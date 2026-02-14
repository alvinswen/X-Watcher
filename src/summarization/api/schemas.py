"""摘要 API 请求/响应模型。

定义 FastAPI 端点使用的 Pydantic 模型。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.shared.schemas import UTCDatetimeModel


class BatchSummaryRequest(BaseModel):
    """批量摘要请求模型。

    用于请求批量处理推文的摘要和翻译。
    """

    tweet_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="推文 ID 列表",
    )
    force_refresh: bool = Field(
        default=False,
        description="是否强制刷新缓存",
    )

    @field_validator("tweet_ids")
    @classmethod
    def validate_tweet_ids(cls, v: list[str]) -> list[str]:
        """验证推文 ID 列表。

        Args:
            v: 推文 ID 列表

        Returns:
            验证后的推文 ID 列表

        Raises:
            ValueError: 如果推文 ID 列表无效
        """
        if not v:
            raise ValueError("tweet_ids 不能为空")

        # 验证每个推文 ID 格式
        for tweet_id in v:
            if not isinstance(tweet_id, str) or not tweet_id.strip():
                raise ValueError(f"无效的推文 ID: {tweet_id}")

        return v


class BatchSummaryResponse(BaseModel):
    """批量摘要响应模型。

    返回批量摘要任务的初始状态。
    """

    task_id: str = Field(..., description="任务 ID")
    status: Literal["pending", "running", "completed", "failed"] = Field(
        ..., description="任务状态"
    )


class SummaryResponse(UTCDatetimeModel):
    """摘要响应模型。

    返回单条推文的摘要和翻译结果。
    """

    summary_id: str = Field(..., description="摘要唯一标识")
    tweet_id: str = Field(..., description="关联的推文 ID")
    summary_text: str = Field(..., description="中文摘要内容")
    translation_text: str | None = Field(None, description="中文翻译内容")
    model_provider: Literal["openrouter", "minimax", "open_source"] = Field(
        ..., description="模型提供商"
    )
    model_name: str = Field(..., description="模型名称")
    prompt_tokens: int = Field(..., ge=0, description="输入 token 数")
    completion_tokens: int = Field(..., ge=0, description="输出 token 数")
    total_tokens: int = Field(..., ge=0, description="总 token 数")
    cost_usd: float = Field(..., ge=0, description="成本（美元）")
    cached: bool = Field(..., description="是否来自缓存")
    content_hash: str = Field(..., description="内容哈希")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @classmethod
    def from_domain(cls, record: "SummaryRecord") -> "SummaryResponse":  # type: ignore[name-defined]
        """从领域模型创建响应。

        Args:
            record: 摘要记录

        Returns:
            摘要响应
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
            content_hash=record.content_hash,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class CostStatsResponse(UTCDatetimeModel):
    """成本统计响应模型。

    返回指定时间范围内的成本统计。
    """

    start_date: datetime | None = Field(None, description="统计开始日期")
    end_date: datetime | None = Field(None, description="统计结束日期")
    total_cost_usd: float = Field(..., ge=0, description="总成本（美元）")
    total_tokens: int = Field(..., ge=0, description="总 token 数")
    prompt_tokens: int = Field(..., ge=0, description="输入 token 总数")
    completion_tokens: int = Field(..., ge=0, description="输出 token 总数")
    provider_breakdown: dict[
        str, dict[str, float | int]
    ] = Field(..., description="按提供商分解的成本和 token")


class SummaryResultResponse(BaseModel):
    """摘要处理结果响应模型。

    返回批量摘要处理的统计结果。
    """

    total_tweets: int = Field(..., ge=0, description="处理的总推文数")
    total_groups: int = Field(..., ge=0, description="处理的去重组数")
    cache_hits: int = Field(..., ge=0, description="缓存命中数")
    cache_misses: int = Field(..., ge=0, description="缓存未命中数")
    total_tokens: int = Field(..., ge=0, description="总 token 使用数")
    total_cost_usd: float = Field(..., ge=0, description="总成本（美元）")
    providers_used: dict[str, int] = Field(
        ..., description="各提供商使用次数"
    )
    processing_time_ms: int = Field(..., ge=0, description="处理耗时（毫秒）")


class ErrorResponse(BaseModel):
    """错误响应模型。

    统一的错误响应格式。
    """

    detail: str = Field(..., description="错误详情")
    error_code: str | None = Field(None, description="错误代码")
