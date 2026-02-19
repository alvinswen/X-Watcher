"""OpenRouter 提供商实现。

.. deprecated::
    此模块已废弃，请使用 `OpenAICompatibleProvider.from_preset("openrouter", ...)` 代替。
    保留此文件仅为向后兼容，内部委托给通用 Provider。
"""

import warnings

from returns.result import Result

from src.summarization.domain.models import LLMResponse
from src.summarization.llm.base import LLMProvider
from src.summarization.llm.openai_compatible import OpenAICompatibleProvider
from src.summarization.llm.presets import OPENROUTER


class OpenRouterProvider(LLMProvider):
    """OpenRouter 提供商（已废弃，委托给 OpenAICompatibleProvider）。

    .. deprecated::
        使用 `OpenAICompatibleProvider.from_preset("openrouter", ...)` 代替。
    """

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
        warnings.warn(
            "OpenRouterProvider 已废弃，请使用 OpenAICompatibleProvider.from_preset('openrouter', ...) 代替",
            DeprecationWarning,
            stacklevel=2,
        )
        self._delegate = OpenAICompatibleProvider(
            provider_name="openrouter",
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            cost_info=OPENROUTER.cost_info,
        )

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> Result[LLMResponse, Exception]:
        return await self._delegate.complete(prompt, max_tokens, temperature)

    def get_provider_name(self) -> str:
        return self._delegate.get_provider_name()

    def get_model_name(self) -> str:
        return self._delegate.get_model_name()
