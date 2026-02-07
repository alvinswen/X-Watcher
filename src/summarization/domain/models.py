"""摘要领域模型。

定义摘要翻译相关的 Pydantic 数据模型。
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LLMErrorType(str, Enum):
    """LLM 错误类型。

    表示 LLM API 调用时的错误分类。
    """

    temporary = "temporary"  # 临时错误：429、超时
    permanent = "permanent"  # 永久错误：401、402


class LLMResponse(BaseModel):
    """LLM 响应模型。

    表示 LLM API 返回的响应数据。
    """

    content: str = Field(..., description="生成的内容")
    model: str = Field(..., description="使用的模型名称")
    provider: Literal["openrouter", "minimax", "open_source"] = Field(
        ..., description="模型提供商"
    )
    prompt_tokens: int = Field(..., ge=0, description="输入 token 数")
    completion_tokens: int = Field(..., ge=0, description="输出 token 数")
    total_tokens: int = Field(..., ge=0, description="总 token 数")
    cost_usd: float = Field(..., ge=0, description="成本（美元）")

    @field_validator("total_tokens")
    @classmethod
    def validate_total_tokens(cls, v: int, info) -> int:
        """验证总 token 数等于输入加输出。"""
        if "prompt_tokens" in info.data and "completion_tokens" in info.data:
            expected = info.data["prompt_tokens"] + info.data["completion_tokens"]
            if v != expected:
                raise ValueError(
                    f"total_tokens ({v}) 必须等于 prompt_tokens + completion_tokens ({expected})"
                )
        return v


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
    model_provider: Literal["openrouter", "minimax", "open_source"] = Field(
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


class SummaryResult(BaseModel):
    """摘要处理结果统计模型。

    表示批量摘要操作的统计结果。
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


class CostStats(BaseModel):
    """成本统计模型。

    表示指定时间范围内的成本统计。
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


class PromptConfig(BaseModel):
    """Prompt 配置模型。

    定义摘要和翻译的 Prompt 模板。
    """

    summary_prompt: str = Field(
        default="""请提取以下推文的关键信息，生成 50-150 字的中文摘要。
要求：
- 保留人名、公司名、产品名等关键实体
- 如果推文包含链接，请在摘要中标注"详情见链接"
- 摘要应简洁明了，突出核心信息

推文内容：{tweet_text}
""",
        description="摘要生成 Prompt 模板",
    )

    translation_prompt: str = Field(
        default="""请将以下英文推文翻译为中文。
要求：
- 保持原文的语气和情感倾向
- 技术术语和专有名词保留原文或提供中英文对照
- URL 链接保持不变，不翻译
- 翻译应自然流畅，符合中文表达习惯

推文内容：{tweet_text}
""",
        description="翻译 Prompt 模板",
    )

    def format_summary(
        self,
        tweet_text: str,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> str:
        """格式化摘要 Prompt。

        Args:
            tweet_text: 推文文本
            min_length: 摘要最小字数（可选）
            max_length: 摘要最大字数（可选）

        Returns:
            格式化后的 Prompt
        """
        # 如果提供了长度参数，动态生成 Prompt
        if min_length is not None and max_length is not None:
            prompt = f"""请提取以下推文的关键信息，生成 {min_length}-{max_length} 字的中文摘要。
要求：
- 保留人名、公司名、产品名等关键实体
- 如果推文包含链接，请在摘要中标注"详情见链接"
- 摘要应简洁明了，突出核心信息

推文内容：{tweet_text}
"""
            return prompt
        # 使用默认模板
        return self.summary_prompt.format(tweet_text=tweet_text)

    def format_translation(self, tweet_text: str) -> str:
        """格式化翻译 Prompt。

        Args:
            tweet_text: 推文文本

        Returns:
            格式化后的 Prompt
        """
        return self.translation_prompt.format(tweet_text=tweet_text)

    # 智能摘要长度配置
    min_tweet_length_for_summary: int = Field(
        default=30,
        ge=1,
        description="推文最小长度，低于此值直接返回原文"
    )
    summary_min_length_ratio: float = Field(
        default=0.5,
        ge=0.1,
        le=1.0,
        description="摘要最小长度为原文的比例"
    )
    summary_max_length_ratio: float = Field(
        default=1.5,
        ge=1.0,
        le=3.0,
        description="摘要最大长度为原文的比例"
    )
