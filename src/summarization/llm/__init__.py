"""LLM 提供商模块。

提供统一的 LLM 调用接口，支持多提供商和智能降级策略。
"""

from src.summarization.llm.base import LLMProvider
from src.summarization.llm.config import (
    LLMProviderConfig,
    MiniMaxConfig,
    OpenRouterConfig,
    OpenSourceConfig,
    ProviderInstanceConfig,
)
from src.summarization.llm.minimax import MiniMaxProvider
from src.summarization.llm.openai_compatible import OpenAICompatibleProvider
from src.summarization.llm.openrouter import OpenRouterProvider
from src.summarization.llm.presets import PROVIDER_PRESETS, ProviderPreset

__all__ = [
    "LLMProvider",
    "LLMProviderConfig",
    "OpenAICompatibleProvider",
    "OpenRouterConfig",
    "MiniMaxConfig",
    "OpenSourceConfig",
    "OpenRouterProvider",
    "MiniMaxProvider",
    "ProviderInstanceConfig",
    "ProviderPreset",
    "PROVIDER_PRESETS",
]
