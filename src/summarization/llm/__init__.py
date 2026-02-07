"""LLM 提供商模块。

提供统一的 LLM 调用接口，支持多提供商和智能降级策略。
"""

from src.summarization.llm.base import LLMProvider
from src.summarization.llm.config import (
    LLMProviderConfig,
    MiniMaxConfig,
    OpenRouterConfig,
    OpenSourceConfig,
)
from src.summarization.llm.minimax import MiniMaxProvider
from src.summarization.llm.openrouter import OpenRouterProvider

__all__ = [
    "LLMProvider",
    "LLMProviderConfig",
    "OpenRouterConfig",
    "MiniMaxConfig",
    "OpenSourceConfig",
    "OpenRouterProvider",
    "MiniMaxProvider",
]
