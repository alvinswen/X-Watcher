"""Provider 预设配置测试。"""

import pytest

from src.summarization.llm.presets import (
    DEEPSEEK,
    MINIMAX,
    MOONSHOT,
    OPENROUTER,
    PROVIDER_PRESETS,
    ZHIPU,
    CostInfo,
    ProviderPreset,
    get_all_slugs,
    get_preset,
)


class TestCostInfo:
    """CostInfo 测试。"""

    def test_calculate_cost_usd_basic(self):
        """测试基本成本计算（USD）。"""
        cost_info = CostInfo(input_cost_per_1k=0.003, output_cost_per_1k=0.015)
        cost = cost_info.calculate_cost_usd(1000, 500)
        assert cost == pytest.approx(0.003 + 0.0075)

    def test_calculate_cost_usd_with_exchange_rate(self):
        """测试含汇率的成本计算（CNY → USD）。"""
        cost_info = CostInfo(
            input_cost_per_1k=0.015,
            output_cost_per_1k=0.015,
            currency="CNY",
            exchange_rate_to_usd=0.14,
        )
        cost = cost_info.calculate_cost_usd(1000, 1000)
        expected = (0.015 + 0.015) * 0.14
        assert cost == pytest.approx(expected)

    def test_calculate_cost_usd_zero_tokens(self):
        """零 token 时成本为零。"""
        cost_info = CostInfo(input_cost_per_1k=0.003, output_cost_per_1k=0.015)
        assert cost_info.calculate_cost_usd(0, 0) == 0.0


class TestProviderPreset:
    """ProviderPreset 测试。"""

    def test_auto_generated_env_key_name(self):
        """测试 env_key_name 自动生成。"""
        preset = ProviderPreset(
            slug="test_provider",
            display_name="Test",
            base_url="https://test.com",
            default_model="test-model",
        )
        assert preset.env_key_name == "LLM_TEST_PROVIDER_API_KEY"

    def test_frozen_dataclass(self):
        """预设是不可变的。"""
        with pytest.raises(AttributeError):
            OPENROUTER.slug = "changed"  # type: ignore


class TestBuiltinPresets:
    """内置预设完整性测试。"""

    def test_all_presets_registered(self):
        """所有预设都已注册。"""
        expected_slugs = {"openrouter", "minimax", "zhipu", "moonshot", "deepseek", "custom"}
        assert set(PROVIDER_PRESETS.keys()) == expected_slugs

    def test_openrouter_preset(self):
        assert OPENROUTER.slug == "openrouter"
        assert "openrouter" in OPENROUTER.base_url
        assert OPENROUTER.default_model == "anthropic/claude-sonnet-4.5"

    def test_minimax_preset(self):
        assert MINIMAX.slug == "minimax"
        assert "minimaxi" in MINIMAX.base_url
        assert MINIMAX.cost_info.currency == "CNY"

    def test_zhipu_preset(self):
        assert ZHIPU.slug == "zhipu"
        assert "bigmodel" in ZHIPU.base_url
        assert ZHIPU.default_model == "glm-4-flash"

    def test_moonshot_preset(self):
        assert MOONSHOT.slug == "moonshot"
        assert "moonshot" in MOONSHOT.base_url

    def test_deepseek_preset(self):
        assert DEEPSEEK.slug == "deepseek"
        assert "deepseek" in DEEPSEEK.base_url
        assert DEEPSEEK.default_model == "deepseek-chat"

    def test_all_presets_have_base_url(self):
        """除 custom 外，所有预设都有 base_url。"""
        for slug, preset in PROVIDER_PRESETS.items():
            if slug != "custom":
                assert preset.base_url, f"{slug} 缺少 base_url"

    def test_all_presets_have_default_model(self):
        """除 custom 外，所有预设都有 default_model。"""
        for slug, preset in PROVIDER_PRESETS.items():
            if slug != "custom":
                assert preset.default_model, f"{slug} 缺少 default_model"


class TestGetPreset:
    """get_preset 函数测试。"""

    def test_get_existing_preset(self):
        assert get_preset("openrouter") is OPENROUTER

    def test_get_preset_case_insensitive(self):
        assert get_preset("OpenRouter") is OPENROUTER

    def test_get_nonexistent_preset(self):
        assert get_preset("nonexistent") is None


class TestGetAllSlugs:
    """get_all_slugs 函数测试。"""

    def test_returns_all_slugs(self):
        slugs = get_all_slugs()
        assert "openrouter" in slugs
        assert "deepseek" in slugs
        assert len(slugs) == len(PROVIDER_PRESETS)
