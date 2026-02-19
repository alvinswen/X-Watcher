"""LLM 提供商配置模型。

定义所有提供商的配置参数和环境变量加载方法。
支持新格式（LLM_PROVIDERS）和旧格式（MINIMAX_API_KEY / OPENROUTER_API_KEY）。
"""

import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

from src.summarization.llm.presets import PROVIDER_PRESETS, get_preset

logger = logging.getLogger(__name__)


# ============================================================
# 新格式：统一提供商实例配置
# ============================================================


class ProviderInstanceConfig(BaseModel):
    """单个 LLM 提供商实例配置。

    可用于任何 OpenAI 兼容的 LLM 服务。
    """

    slug: str = Field(..., description="提供商标识（如 openrouter, deepseek）")
    api_key: str = Field(..., description="API 密钥")
    base_url: str = Field(default="", description="API 基础 URL（空则使用预设默认值）")
    model: str = Field(default="", description="模型名称（空则使用预设默认值）")
    timeout_seconds: int = Field(default=30, ge=1, description="请求超时时间（秒）")
    max_retries: int = Field(default=1, ge=0, description="最大重试次数")


def get_provider_instances_from_env() -> list[ProviderInstanceConfig]:
    """从新格式环境变量加载提供商配置列表。

    环境变量格式：
        LLM_PROVIDERS=openrouter,deepseek
        LLM_OPENROUTER_API_KEY=sk-xxx
        LLM_OPENROUTER_MODEL=anthropic/claude-sonnet-4.5  # 可选覆盖
        LLM_DEEPSEEK_API_KEY=sk-yyy

    Returns:
        按优先级排序的提供商配置列表
    """
    providers_str = os.getenv("LLM_PROVIDERS", "").strip()
    if not providers_str:
        return []

    slugs = [s.strip().lower() for s in providers_str.split(",") if s.strip()]
    instances: list[ProviderInstanceConfig] = []

    for slug in slugs:
        prefix = f"LLM_{slug.upper()}_"
        api_key = os.getenv(f"{prefix}API_KEY", "").strip()

        if not api_key:
            logger.warning(f"LLM_PROVIDERS 中指定了 {slug}，但未找到 {prefix}API_KEY，跳过")
            continue

        preset = get_preset(slug)
        default_base_url = preset.base_url if preset else ""
        default_model = preset.default_model if preset else ""

        instances.append(
            ProviderInstanceConfig(
                slug=slug,
                api_key=api_key,
                base_url=os.getenv(f"{prefix}BASE_URL", default_base_url),
                model=os.getenv(f"{prefix}MODEL", default_model),
                timeout_seconds=int(os.getenv(f"{prefix}TIMEOUT_SECONDS", "30")),
                max_retries=int(os.getenv(f"{prefix}MAX_RETRIES", "1")),
            )
        )

    return instances


# ============================================================
# 旧格式：保持向后兼容
# ============================================================


class OpenRouterConfig(BaseModel):
    """OpenRouter 提供商配置。

    定义 OpenRouter API 的连接参数。
    """

    api_key: str = Field(..., description="OpenRouter API 密钥")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1", description="API 基础 URL"
    )
    model: str = Field(
        default="anthropic/claude-sonnet-4.5", description="模型名称"
    )
    timeout_seconds: int = Field(default=30, ge=1, description="请求超时时间（秒）")
    max_retries: int = Field(default=1, ge=0, description="最大重试次数")

    @classmethod
    def from_env(cls) -> "OpenRouterConfig | None":
        """从环境变量加载配置。

        Returns:
            OpenRouterConfig 或 None（如果未配置 API 密钥）
        """
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return None

        return cls(
            api_key=api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5"),
            timeout_seconds=int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("OPENROUTER_MAX_RETRIES", "1")),
        )


class MiniMaxConfig(BaseModel):
    """MiniMax 中国版提供商配置。

    定义 MiniMax 中国版 API 的连接参数。
    """

    api_key: str = Field(..., description="MiniMax API 密钥")
    base_url: str = Field(
        default="https://api.minimaxi.com", description="API 基础 URL（中国版）"
    )
    model: str = Field(default="abab6.5s-chat", description="模型名称（M2.1）")
    group_id: str | None = Field(default=None, description="分组 ID（可选）")
    timeout_seconds: int = Field(default=30, ge=1, description="请求超时时间（秒）")
    max_retries: int = Field(default=1, ge=0, description="最大重试次数")

    @classmethod
    def from_env(cls) -> "MiniMaxConfig | None":
        """从环境变量加载配置。

        Returns:
            MiniMaxConfig 或 None（如果未配置 API 密钥）
        """
        api_key = os.getenv("MINIMAX_API_KEY", "")
        if not api_key:
            return None

        return cls(
            api_key=api_key,
            base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com"),
            model=os.getenv("MINIMAX_MODEL", "abab6.5s-chat"),
            group_id=os.getenv("MINIMAX_GROUP_ID"),
            timeout_seconds=int(os.getenv("MINIMAX_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("MINIMAX_MAX_RETRIES", "1")),
        )


class OpenSourceConfig(BaseModel):
    """开源模型提供商配置（预留扩展）。

    定义自托管或第三方开源模型 API 的连接参数。
    """

    api_key: str = Field(..., description="API 密钥")
    base_url: str = Field(..., description="API 基础 URL")
    model: str = Field(..., description="模型名称")
    provider: Literal["ollama", "vllm", "custom"] = Field(
        default="custom", description="提供商类型"
    )
    timeout_seconds: int = Field(default=60, ge=1, description="请求超时时间（秒）")
    max_retries: int = Field(default=1, ge=0, description="最大重试次数")

    @classmethod
    def from_env(cls) -> "OpenSourceConfig | None":
        """从环境变量加载配置。

        Returns:
            OpenSourceConfig 或 None（如果未配置）
        """
        api_key = os.getenv("OPEN_SOURCE_API_KEY", "")
        base_url = os.getenv("OPEN_SOURCE_BASE_URL", "")
        model = os.getenv("OPEN_SOURCE_MODEL", "")

        if not base_url or not model:
            return None

        return cls(
            api_key=api_key or "no-key",  # 本地模型可能不需要 API 密钥
            base_url=base_url,
            model=model,
            provider=os.getenv("OPEN_SOURCE_PROVIDER", "custom"),  # type: ignore
            timeout_seconds=int(os.getenv("OPEN_SOURCE_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("OPEN_SOURCE_MAX_RETRIES", "1")),
        )


# ============================================================
# 聚合配置
# ============================================================


class LLMProviderConfig(BaseModel):
    """LLM 提供商聚合配置。

    包含所有提供商的配置，支持从环境变量统一加载。
    优先使用新格式（LLM_PROVIDERS），回退到旧格式（MINIMAX_API_KEY 等）。
    """

    # 旧格式字段（向后兼容）
    openrouter: OpenRouterConfig | None = Field(
        default=None, description="OpenRouter 配置"
    )
    minimax: MiniMaxConfig | None = Field(
        default=None, description="MiniMax 配置"
    )
    open_source: OpenSourceConfig | None = Field(
        default=None, description="开源模型配置"
    )

    # 新格式字段
    unified_providers: list[ProviderInstanceConfig] = Field(
        default_factory=list, description="统一格式的提供商配置列表（按优先级排序）"
    )

    @classmethod
    def from_env(cls) -> "LLMProviderConfig":
        """从环境变量加载所有提供商配置。

        优先使用新格式（LLM_PROVIDERS），如果未设置则回退到旧格式。

        Returns:
            LLMProviderConfig: 包含所有已配置提供商的配置
        """
        # 尝试新格式
        unified = get_provider_instances_from_env()

        # 加载旧格式（始终加载，用于向后兼容）
        openrouter = OpenRouterConfig.from_env()
        minimax = MiniMaxConfig.from_env()
        open_source = OpenSourceConfig.from_env()

        return cls(
            openrouter=openrouter,
            minimax=minimax,
            open_source=open_source,
            unified_providers=unified,
        )

    def has_any_provider(self) -> bool:
        """检查是否配置了至少一个提供商。

        Returns:
            是否至少有一个可用提供商
        """
        return (
            len(self.unified_providers) > 0
            or self.openrouter is not None
            or self.minimax is not None
            or self.open_source is not None
        )

    def get_providers(self) -> list[str]:
        """获取已配置的提供商列表（按优先级排序）。

        新格式优先，否则回退到旧格式。

        Returns:
            已配置的提供商名称列表
        """
        if self.unified_providers:
            return [p.slug for p in self.unified_providers]

        providers: list[str] = []
        if self.openrouter:
            providers.append("openrouter")
        if self.minimax:
            providers.append("minimax")
        if self.open_source:
            providers.append("open_source")
        return providers

    def uses_unified_format(self) -> bool:
        """是否使用了新的统一配置格式。"""
        return len(self.unified_providers) > 0
