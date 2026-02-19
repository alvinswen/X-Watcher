"""通用 OpenAI 兼容 LLM 提供商实现。

替代原有的 OpenRouterProvider 和 MiniMaxProvider，
用单一实现支持所有兼容 OpenAI Chat Completions 协议的 LLM 服务。
"""

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from returns.result import Failure, Result, Success

from src.summarization.domain.models import LLMErrorType, LLMResponse
from src.summarization.llm.base import LLMProvider, classify_error
from src.summarization.llm.presets import CostInfo, ProviderPreset, get_preset


class OpenAICompatibleProvider(LLMProvider):
    """通用 OpenAI 兼容提供商。

    支持所有兼容 OpenAI Chat Completions API 的 LLM 服务，
    包括 OpenRouter、MiniMax、智谱、Moonshot、DeepSeek 等。
    """

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 30,
        max_retries: int = 1,
        cost_info: CostInfo | None = None,
    ) -> None:
        """初始化通用 Provider。

        Args:
            provider_name: 提供商标识名（如 "openrouter", "deepseek"）
            api_key: API 密钥
            base_url: API 基础 URL
            model: 模型名称
            timeout_seconds: 请求超时时间（秒）
            max_retries: 最大重试次数
            cost_info: 成本信息（用于估算费用）
        """
        self._provider_name = provider_name
        self._model = model
        self._cost_info = cost_info or CostInfo()
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @classmethod
    def from_preset(
        cls,
        slug: str,
        api_key: str,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
    ) -> "OpenAICompatibleProvider":
        """从预设创建 Provider 实例。

        Args:
            slug: 提供商标识（如 "openrouter", "deepseek"）
            api_key: API 密钥
            base_url: 覆盖预设的 base_url（可选）
            model: 覆盖预设的 model（可选）
            timeout_seconds: 覆盖预设的超时（可选）
            max_retries: 覆盖预设的重试次数（可选）

        Returns:
            OpenAICompatibleProvider 实例

        Raises:
            ValueError: 未找到对应的预设
        """
        preset = get_preset(slug)
        if preset is None:
            raise ValueError(f"未知的 LLM 提供商: {slug}")

        return cls(
            provider_name=preset.slug,
            api_key=api_key,
            base_url=base_url or preset.base_url,
            model=model or preset.default_model,
            timeout_seconds=timeout_seconds or preset.default_timeout_seconds,
            max_retries=max_retries if max_retries is not None else preset.default_max_retries,
            cost_info=preset.cost_info,
        )

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> Result[LLMResponse, Exception]:
        """调用 LLM API 生成文本。

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
            status_code = _extract_status_code(e)
            error_type = classify_error(status_code) if status_code else None

            if error_type:
                return Failure(
                    _ProviderError(
                        str(e),
                        provider=self._provider_name,
                        status_code=status_code,
                        error_type=error_type,
                    )
                )
            return Failure(e)

    def _parse_response(self, response: ChatCompletion) -> Result[LLMResponse, Exception]:
        """解析 API 响应。"""
        try:
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason

            if not content:
                return Failure(ValueError(f"{self._provider_name} 返回空内容"))

            usage = response.usage
            if not usage:
                return Failure(ValueError(f"{self._provider_name} 未返回 token 使用信息"))

            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens

            cost_usd = self._cost_info.calculate_cost_usd(prompt_tokens, completion_tokens)

            return Success(
                LLMResponse(
                    content=content,
                    model=response.model,
                    provider=self._provider_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    finish_reason=finish_reason,
                )
            )

        except (IndexError, KeyError, AttributeError) as e:
            return Failure(ValueError(f"解析 {self._provider_name} 响应失败: {e}"))

    def get_provider_name(self) -> str:
        """获取提供商名称。"""
        return self._provider_name

    def get_model_name(self) -> str:
        """获取模型名称。"""
        return self._model


class _ProviderError(Exception):
    """通用提供商错误。

    包含状态码和错误类型信息，用于降级决策。
    """

    def __init__(
        self,
        message: str,
        provider: str = "",
        status_code: int | None = None,
        error_type: LLMErrorType | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.error_type = error_type


def _extract_status_code(error: Exception) -> int | None:
    """从异常中提取 HTTP 状态码。"""
    if hasattr(error, "status_code"):
        return int(getattr(error, "status_code"))
    return None
