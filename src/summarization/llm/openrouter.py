"""OpenRouter 提供商实现。

封装 OpenRouter API 调用，使用 Anthropic Claude Sonnet 4.5 模型。
"""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from openai.types import Completion
from returns.result import Failure, Result, Success

from src.summarization.domain.models import LLMResponse
from src.summarization.llm.base import LLMProvider, classify_error

# OpenRouter 定价（美元/1K tokens）
# 基于 https://openrouter.ai/docs#models
# anthropic/claude-sonnet-4.5: Input $3, Output $15
INPUT_COST_PER_1K_TOKENS = 0.003
OUTPUT_COST_PER_1K_TOKENS = 0.015


class OpenRouterProvider(LLMProvider):
    """OpenRouter 提供商。

    使用 OpenRouter API 调用 Anthropic Claude Sonnet 4.5 模型。
    """

    # 默认配置
    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
    DEFAULT_TIMEOUT_SECONDS = 30
    DEFAULT_MAX_RETRIES = 1

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """初始化 OpenRouter 提供商。

        Args:
            api_key: OpenRouter API 密钥
            base_url: API 基础 URL
            model: 模型名称
            timeout_seconds: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._model = model

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> Result[LLMResponse, Exception]:
        """调用 OpenRouter API 生成文本。

        Args:
            prompt: 输入提示词
            max_tokens: 最大输出 token 数
            temperature: 温度参数

        Returns:
            Result[LLMResponse, Exception]: 成功返回响应，失败返回错误
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            return self._parse_response(response)

        except Exception as e:
            # 尝试从异常中提取状态码进行分类
            status_code = _extract_status_code(e)
            error_type = classify_error(status_code) if status_code else None

            # 构造带有错误类型信息的异常
            if error_type:
                return Failure(
                    _OpenRouterError(
                        str(e), status_code=status_code, error_type=error_type
                    )
                )
            return Failure(e)

    def _parse_response(self, response: Completion) -> Result[LLMResponse, Exception]:
        """解析 OpenRouter API 响应。

        Args:
            response: OpenAI SDK 响应对象

        Returns:
            Result[LLMResponse, Exception]: 解析后的响应
        """
        try:
            choice = response.choices[0]
            content = choice.message.content or ""

            if not content:
                return Failure(ValueError("OpenRouter 返回空内容"))

            usage = response.usage
            if not usage:
                return Failure(ValueError("OpenRouter 未返回 token 使用信息"))

            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens

            # 计算成本
            cost_usd = (
                prompt_tokens * INPUT_COST_PER_1K_TOKENS / 1000
                + completion_tokens * OUTPUT_COST_PER_1K_TOKENS / 1000
            )

            return Success(
                LLMResponse(
                    content=content,
                    model=response.model,
                    provider="openrouter",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                )
            )

        except (IndexError, KeyError, AttributeError) as e:
            return Failure(ValueError(f"解析 OpenRouter 响应失败: {e}"))

    def get_provider_name(self) -> str:
        """获取提供商名称。

        Returns:
            提供商名称
        """
        return "openrouter"

    def get_model_name(self) -> str:
        """获取模型名称。

        Returns:
            模型名称
        """
        return self._model


class _OpenRouterError(Exception):
    """OpenRouter 错误。

    包含状态码和错误类型信息，用于降级决策。
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: "src.summarization.domain.models.LLMErrorType | None" = None,
    ) -> None:
        """初始化错误。

        Args:
            message: 错误消息
            status_code: HTTP 状态码
            error_type: 错误类型
        """
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


def _extract_status_code(error: Exception) -> int | None:
    """从异常中提取 HTTP 状态码。

    Args:
        error: 异常对象

    Returns:
        HTTP 状态码或 None
    """
    # OpenAI SDK 异常通常包含 status_code 属性
    if hasattr(error, "status_code"):
        return int(getattr(error, "status_code"))
    return None
