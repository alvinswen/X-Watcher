"""通用 OpenAI 兼容 Provider 测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.summarization.llm.openai_compatible import OpenAICompatibleProvider, _ProviderError
from src.summarization.llm.presets import CostInfo


class TestOpenAICompatibleProviderInit:
    """Provider 初始化测试。"""

    def test_basic_init(self):
        """基本初始化。"""
        provider = OpenAICompatibleProvider(
            provider_name="test",
            api_key="sk-test",
            base_url="https://api.test.com/v1",
            model="test-model",
        )
        assert provider.get_provider_name() == "test"
        assert provider.get_model_name() == "test-model"

    def test_from_preset_openrouter(self):
        """从 OpenRouter 预设创建。"""
        provider = OpenAICompatibleProvider.from_preset(
            "openrouter", api_key="sk-test"
        )
        assert provider.get_provider_name() == "openrouter"
        assert provider.get_model_name() == "anthropic/claude-sonnet-4.6"

    def test_from_preset_deepseek(self):
        """从 DeepSeek 预设创建。"""
        provider = OpenAICompatibleProvider.from_preset(
            "deepseek", api_key="sk-test"
        )
        assert provider.get_provider_name() == "deepseek"
        assert provider.get_model_name() == "deepseek-chat"

    def test_from_preset_with_overrides(self):
        """预设参数可被覆盖。"""
        provider = OpenAICompatibleProvider.from_preset(
            "openrouter",
            api_key="sk-test",
            model="custom-model",
        )
        assert provider.get_model_name() == "custom-model"

    def test_from_preset_unknown_slug(self):
        """未知 slug 抛出 ValueError。"""
        with pytest.raises(ValueError, match="未知的 LLM 提供商"):
            OpenAICompatibleProvider.from_preset("nonexistent", api_key="sk-test")


class TestOpenAICompatibleProviderComplete:
    """Provider complete() 方法测试。"""

    @pytest.fixture
    def provider(self):
        """创建测试用 Provider。"""
        return OpenAICompatibleProvider(
            provider_name="test",
            api_key="sk-test",
            base_url="https://api.test.com/v1",
            model="test-model",
            cost_info=CostInfo(input_cost_per_1k=0.001, output_cost_per_1k=0.002),
        )

    async def test_successful_completion(self, provider):
        """成功调用返回 LLMResponse。"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "test-model"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        with patch.object(
            provider._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            result = await provider.complete("test prompt")

        from returns.result import Success

        assert isinstance(result, Success)
        response = result.unwrap()
        assert response.content == "Hello!"
        assert response.provider == "test"
        assert response.model == "test-model"
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 5
        assert response.total_tokens == 15
        assert response.cost_usd > 0

    async def test_empty_content_returns_failure(self, provider):
        """空内容返回 Failure。"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "test-model"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 0
        mock_response.usage.total_tokens = 10

        with patch.object(
            provider._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            result = await provider.complete("test")

        from returns.result import Failure

        assert isinstance(result, Failure)

    async def test_api_error_with_status_code(self, provider):
        """API 错误包含状态码信息。"""
        error = Exception("Rate limited")
        error.status_code = 429  # type: ignore

        with patch.object(
            provider._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = error
            result = await provider.complete("test")

        from returns.result import Failure

        assert isinstance(result, Failure)
        err = result.failure()
        assert isinstance(err, _ProviderError)
        assert err.status_code == 429


class TestProviderError:
    """_ProviderError 测试。"""

    def test_error_attributes(self):
        from src.summarization.domain.models import LLMErrorType

        err = _ProviderError(
            "test error",
            provider="openrouter",
            status_code=429,
            error_type=LLMErrorType.temporary,
        )
        assert err.provider == "openrouter"
        assert err.status_code == 429
        assert err.error_type == LLMErrorType.temporary
        assert str(err) == "test error"
