"""关注列表管理验证器。

提供 Twitter 用户名的独立验证器。
"""

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    """错误代码枚举。"""

    EMPTY_VALUE = "EMPTY_VALUE"
    TOO_LONG = "TOO_LONG"
    INVALID_FORMAT = "INVALID_FORMAT"


@dataclass
class ValidationResult:
    """验证结果数据类。

    表示验证操作的最终结果。
    """

    is_valid: bool
    """是否验证通过"""

    normalized: str | None = None
    """标准化后的值（仅当验证通过时）"""

    error_code: str | None = None
    """错误代码（仅当验证失败时）"""

    error_message: str | None = None
    """错误消息（仅当验证失败时）"""


class ValidationError(Exception):
    """验证错误异常。

    当验证失败时可以抛出此异常。
    """

    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class TwitterUsernameValidator:
    """Twitter 用户名验证器。

    验证 Twitter 用户名是否符合规则：
    - 1-15 字符
    - 只包含字母、数字和下划线
    - 可以有前导 @ 符号（会被去除）
    - 大小写不敏感（会转换为小写）
    """

    MAX_LENGTH = 15
    """用户名最大长度"""

    def validate(self, username: str) -> ValidationResult:
        """验证 Twitter 用户名。

        Args:
            username: 待验证的用户名

        Returns:
            验证结果对象
        """
        if not username:
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.EMPTY_VALUE,
                error_message="用户名不能为空",
            )

        # 去除前导 @ 符号并转换为小写
        normalized = username.lstrip("@").lower()

        # 检查是否为空（去除 @ 后）
        if not normalized:
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.EMPTY_VALUE,
                error_message="用户名不能为空",
            )

        # 检查长度
        if len(normalized) > self.MAX_LENGTH:
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.TOO_LONG,
                error_message=f"用户名不能超过 {self.MAX_LENGTH} 个字符",
            )

        # 检查字符有效性（只允许字母、数字、下划线）
        if not normalized.replace("_", "").isalnum():
            return ValidationResult(
                is_valid=False,
                error_code=ErrorCode.INVALID_FORMAT,
                error_message=(
                    "用户名只能包含字母、数字和下划线，"
                    "且不能以 @ 符号开头"
                ),
            )

        return ValidationResult(is_valid=True, normalized=normalized)

    def validate_or_raise(self, username: str) -> str:
        """验证用户名，失败时抛出异常。

        Args:
            username: 待验证的用户名

        Returns:
            标准化后的用户名

        Raises:
            ValidationError: 如果验证失败
        """
        result = self.validate(username)
        if not result.is_valid:
            raise ValidationError(
                error_code=result.error_code or "UNKNOWN",
                message=result.error_message or "验证失败",
            )
        return result.normalized  # type: ignore[return-value]
