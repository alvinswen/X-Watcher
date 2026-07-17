"""摘要 API 请求/响应模型。

定义 FastAPI 端点使用的 Pydantic 模型。
"""

from datetime import datetime

from pydantic import Field

from src.shared.schemas import UTCDatetimeModel


class SummaryResponse(UTCDatetimeModel):
    """摘要响应模型。

    返回单条推文的摘要和翻译结果。
    """

    summary_id: str = Field(..., description="摘要唯一标识")
    tweet_id: str = Field(..., description="关联的推文 ID")
    summary_text: str = Field(..., description="中文摘要内容")
    translation_text: str | None = Field(None, description="中文翻译内容")
    model_provider: str = Field(
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
