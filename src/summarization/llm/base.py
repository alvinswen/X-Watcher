"""LLM 提供商抽象基类。

定义统一的 LLM 调用接口和错误分类常量。
"""

from abc import ABC, abstractmethod
from typing import Final

from returns.result import Result

from src.summarization.domain.models import LLMResponse, LLMErrorType


# 错误分类常量
TEMPORARY_ERRORS: Final[tuple[int, ...]] = (429, 503, 504)  # 速率限制、服务不可用
PERMANENT_ERRORS: Final[tuple[int, ...]] = (401, 402)  # 认证失败、余额不足


def classify_error(status_code: int) -> LLMErrorType | None:
    """根据 HTTP 状态码分类错误类型。

    Args:
        status_code: HTTP 状态码

    Returns:
        LLMErrorType 或 None（如果不是已知错误类型）
    """
    if status_code in TEMPORARY_ERRORS:
        return LLMErrorType.temporary
    if status_code in PERMANENT_ERRORS:
        return LLMErrorType.permanent
    return None


class LLMProvider(ABC):
    """LLM 提供商抽象基类。

    定义所有 LLM 提供商必须实现的接口。
    """

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> Result[LLMResponse, Exception]:
        """调用 LLM 生成文本。

        Args:
            prompt: 输入提示词
            max_tokens: 最大输出 token 数
            temperature: 温度参数

        Returns:
            Result[LLMResponse, Exception]: 成功返回响应，失败返回错误

        Preconditions:
            - API Key 已配置且有效
            - prompt 非空
            - max_tokens > 0

        Postconditions:
            - 返回的 content 非空
            - token 统计准确
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """获取提供商名称。

        Returns:
            提供商名称（openrouter, minimax, open_source）
        """
        pass
