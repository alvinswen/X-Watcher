"""摘要领域模型。

定义摘要翻译相关的 Pydantic 数据模型。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SummaryRecord(BaseModel):
    """摘要记录模型。

    表示一条推文的摘要和翻译结果，可持久化到数据库。
    """

    summary_id: str = Field(..., description="摘要唯一标识（UUID）")
    tweet_id: str = Field(..., description="关联的推文 ID")
    summary_text: str = Field(
        ..., min_length=1, max_length=500, description="中文摘要内容"
    )
    translation_text: str | None = Field(None, description="中文翻译内容")
    model_provider: str = Field(
        ..., description="模型提供商"
    )
    model_name: str = Field(..., description="模型名称")
    prompt_tokens: int = Field(..., ge=0, description="输入 token 数")
    completion_tokens: int = Field(..., ge=0, description="输出 token 数")
    total_tokens: int = Field(..., ge=0, description="总 token 数")
    cost_usd: float = Field(..., ge=0, description="成本（美元）")
    cached: bool = Field(default=False, description="是否来自缓存")
    is_generated_summary: bool = Field(
        default=True, description="是否为生成的摘要（False表示原文太短直接返回）"
    )
    content_hash: str = Field(..., min_length=1, description="内容哈希（缓存键）")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
