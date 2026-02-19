"""统一 LLM 配置加载测试。

验证新格式（LLM_PROVIDERS）和旧格式（MINIMAX_API_KEY 等）都能正确加载。
"""

from unittest.mock import patch

import pytest

from src.summarization.llm.config import (
    LLMProviderConfig,
    ProviderInstanceConfig,
    get_provider_instances_from_env,
)


class TestGetProviderInstancesFromEnv:
    """新格式环境变量加载测试。"""

    def test_empty_when_no_env(self):
        """未设置 LLM_PROVIDERS 时返回空列表。"""
        with patch.dict("os.environ", {"LLM_PROVIDERS": ""}, clear=False):
            instances = get_provider_instances_from_env()
            assert instances == []

    def test_single_provider(self):
        """单个提供商配置。"""
        env = {
            "LLM_PROVIDERS": "deepseek",
            "LLM_DEEPSEEK_API_KEY": "sk-test",
        }
        with patch.dict("os.environ", env, clear=False):
            instances = get_provider_instances_from_env()
            assert len(instances) == 1
            assert instances[0].slug == "deepseek"
            assert instances[0].api_key == "sk-test"
            assert instances[0].base_url == "https://api.deepseek.com/v1"
            assert instances[0].model == "deepseek-chat"

    def test_multiple_providers(self):
        """多个提供商按优先级排序。"""
        env = {
            "LLM_PROVIDERS": "openrouter,deepseek",
            "LLM_OPENROUTER_API_KEY": "sk-or",
            "LLM_DEEPSEEK_API_KEY": "sk-ds",
        }
        with patch.dict("os.environ", env, clear=False):
            instances = get_provider_instances_from_env()
            assert len(instances) == 2
            assert instances[0].slug == "openrouter"
            assert instances[1].slug == "deepseek"

    def test_skip_missing_api_key(self):
        """缺少 API Key 的提供商被跳过。"""
        env = {
            "LLM_PROVIDERS": "openrouter,deepseek",
            "LLM_OPENROUTER_API_KEY": "sk-or",
            # LLM_DEEPSEEK_API_KEY 未设置
        }
        with patch.dict("os.environ", env, clear=False):
            # 确保 LLM_DEEPSEEK_API_KEY 不存在
            import os
            os.environ.pop("LLM_DEEPSEEK_API_KEY", None)
            instances = get_provider_instances_from_env()
            assert len(instances) == 1
            assert instances[0].slug == "openrouter"

    def test_custom_base_url_override(self):
        """覆盖默认 base_url。"""
        env = {
            "LLM_PROVIDERS": "deepseek",
            "LLM_DEEPSEEK_API_KEY": "sk-test",
            "LLM_DEEPSEEK_BASE_URL": "https://custom.endpoint.com/v1",
        }
        with patch.dict("os.environ", env, clear=False):
            instances = get_provider_instances_from_env()
            assert instances[0].base_url == "https://custom.endpoint.com/v1"

    def test_custom_model_override(self):
        """覆盖默认模型。"""
        env = {
            "LLM_PROVIDERS": "openrouter",
            "LLM_OPENROUTER_API_KEY": "sk-test",
            "LLM_OPENROUTER_MODEL": "meta-llama/llama-3-70b",
        }
        with patch.dict("os.environ", env, clear=False):
            instances = get_provider_instances_from_env()
            assert instances[0].model == "meta-llama/llama-3-70b"


class TestLLMProviderConfigFromEnv:
    """LLMProviderConfig.from_env() 测试。"""

    def test_new_format_priority(self):
        """新格式优先于旧格式。"""
        env = {
            "LLM_PROVIDERS": "deepseek",
            "LLM_DEEPSEEK_API_KEY": "sk-new",
            "MINIMAX_API_KEY": "old-key",
        }
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            assert config.uses_unified_format()
            assert len(config.unified_providers) == 1
            # 旧格式也被加载（向后兼容）
            assert config.minimax is not None

    def test_fallback_to_legacy_format(self):
        """无 LLM_PROVIDERS 时回退到旧格式。"""
        env = {
            "LLM_PROVIDERS": "",
            "MINIMAX_API_KEY": "old-key",
            "OPENROUTER_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            assert not config.uses_unified_format()
            assert config.minimax is not None
            assert config.minimax.api_key == "old-key"

    def test_has_any_provider_new_format(self):
        env = {
            "LLM_PROVIDERS": "deepseek",
            "LLM_DEEPSEEK_API_KEY": "sk-test",
            "MINIMAX_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            assert config.has_any_provider()

    def test_has_any_provider_legacy_format(self):
        env = {"LLM_PROVIDERS": "", "MINIMAX_API_KEY": "key", "OPENROUTER_API_KEY": ""}
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            assert config.has_any_provider()

    def test_no_provider(self):
        env = {
            "LLM_PROVIDERS": "",
            "MINIMAX_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "OPEN_SOURCE_BASE_URL": "",
            "OPEN_SOURCE_MODEL": "",
        }
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            assert not config.has_any_provider()

    def test_get_providers_new_format(self):
        env = {
            "LLM_PROVIDERS": "openrouter,deepseek",
            "LLM_OPENROUTER_API_KEY": "sk-or",
            "LLM_DEEPSEEK_API_KEY": "sk-ds",
        }
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            providers = config.get_providers()
            assert providers == ["openrouter", "deepseek"]

    def test_get_providers_legacy_format(self):
        env = {
            "LLM_PROVIDERS": "",
            "OPENROUTER_API_KEY": "key",
            "MINIMAX_API_KEY": "key",
        }
        with patch.dict("os.environ", env, clear=False):
            config = LLMProviderConfig.from_env()
            providers = config.get_providers()
            assert "openrouter" in providers
            assert "minimax" in providers
