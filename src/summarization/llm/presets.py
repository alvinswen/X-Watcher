"""LLM 提供商预设配置。

内置各提供商的默认 base_url、模型名称和成本信息，
用于简化配置流程——用户只需提供 provider slug + API Key 即可。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CostInfo:
    """LLM 成本信息（美元/1K tokens）。"""

    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    currency: str = "USD"
    exchange_rate_to_usd: float = 1.0

    def calculate_cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float:
        """计算实际成本（美元）。"""
        raw_cost = (
            prompt_tokens * self.input_cost_per_1k / 1000
            + completion_tokens * self.output_cost_per_1k / 1000
        )
        return raw_cost * self.exchange_rate_to_usd


@dataclass(frozen=True)
class ProviderPreset:
    """LLM 提供商预设。"""

    slug: str
    display_name: str
    base_url: str
    default_model: str
    cost_info: CostInfo = field(default_factory=CostInfo)
    default_timeout_seconds: int = 30
    default_max_retries: int = 1
    env_key_name: str = ""  # 对应的环境变量名（如 LLM_OPENROUTER_API_KEY）

    def __post_init__(self) -> None:
        if not self.env_key_name:
            object.__setattr__(
                self, "env_key_name", f"LLM_{self.slug.upper()}_API_KEY"
            )


# ============================================================
# 内置提供商预设
# ============================================================

PROVIDER_PRESETS: dict[str, ProviderPreset] = {}


def _register(preset: ProviderPreset) -> ProviderPreset:
    PROVIDER_PRESETS[preset.slug] = preset
    return preset


OPENROUTER = _register(
    ProviderPreset(
        slug="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-sonnet-4.6",
        cost_info=CostInfo(input_cost_per_1k=0.003, output_cost_per_1k=0.015),
    )
)

MINIMAX = _register(
    ProviderPreset(
        slug="minimax",
        display_name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        default_model="MiniMax-M2.5",
        cost_info=CostInfo(
            input_cost_per_1k=0.015,
            output_cost_per_1k=0.015,
            currency="CNY",
            exchange_rate_to_usd=0.14,
        ),
    )
)

ZHIPU = _register(
    ProviderPreset(
        slug="zhipu",
        display_name="Zhipu AI",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5",
        cost_info=CostInfo(
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.001,
            currency="CNY",
            exchange_rate_to_usd=0.14,
        ),
    )
)

MOONSHOT = _register(
    ProviderPreset(
        slug="moonshot",
        display_name="Moonshot (Kimi)",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2.5",
        cost_info=CostInfo(
            input_cost_per_1k=0.012,
            output_cost_per_1k=0.012,
            currency="CNY",
            exchange_rate_to_usd=0.14,
        ),
    )
)

DEEPSEEK = _register(
    ProviderPreset(
        slug="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        cost_info=CostInfo(
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            currency="CNY",
            exchange_rate_to_usd=0.14,
        ),
    )
)

CUSTOM = _register(
    ProviderPreset(
        slug="custom",
        display_name="Custom (OpenAI-compatible)",
        base_url="",  # 用户必须提供
        default_model="",  # 用户必须提供
        cost_info=CostInfo(),
    )
)


def get_preset(slug: str) -> ProviderPreset | None:
    """根据 slug 获取预设配置。"""
    return PROVIDER_PRESETS.get(slug.lower())


def get_all_slugs() -> list[str]:
    """获取所有可用的 provider slug 列表。"""
    return list(PROVIDER_PRESETS.keys())
