"""关注列表管理验证器单元测试。

测试 Twitter 用户名验证器。
"""

import pytest

from src.preference.domain.validators import (
    TwitterUsernameValidator,
    ValidationError,
)


class TestTwitterUsernameValidator:
    """Twitter 用户名验证器测试。"""

    def test_validate_valid_username(self):
        """测试验证有效的用户名。"""
        valid_usernames = [
            "karpathy",
            "ylecun",
            "samalt",
            "test_user",
            "user123",
            "a",  # 最短
            "abcdefghijklmno",  # 最长（15字符）
        ]
        validator = TwitterUsernameValidator()

        for username in valid_usernames:
            result = validator.validate(username)
            assert result.is_valid
            assert result.normalized == username.lower()

    def test_validate_username_with_at_symbol(self):
        """测试验证带 @ 符号的用户名。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("@karpathy")

        assert result.is_valid
        assert result.normalized == "karpathy"

    def test_validate_uppercase_username(self):
        """测试验证大写用户名（应转换为小写）。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("KARPATHY")

        assert result.is_valid
        assert result.normalized == "karpathy"

    def test_validate_username_too_long(self):
        """测试验证超过 15 字符的用户名。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("thisusernameistoolong")

        assert not result.is_valid
        assert "超过 15 个字符" in result.error_message

    def test_validate_username_with_special_chars(self):
        """测试验证包含特殊字符的用户名。"""
        validator = TwitterUsernameValidator()
        invalid_usernames = [
            "user@name",
            "user-name",
            "user.name",
            "user name",
            "user!",
        ]

        for username in invalid_usernames:
            result = validator.validate(username)
            assert not result.is_valid
            assert "只能包含" in result.error_message

    def test_validate_empty_username(self):
        """测试验证空用户名。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("")

        assert not result.is_valid
        assert "不能为空" in result.error_message

    def test_validate_only_at_symbol(self):
        """测试验证只有 @ 符号的输入。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("@")

        assert not result.is_valid

    def test_validate_username_starting_with_number(self):
        """测试验证以数字开头的用户名（有效）。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("123user")

        assert result.is_valid
        assert result.normalized == "123user"

    def test_validate_username_ending_with_underscore(self):
        """测试验证以下划线结尾的用户名（有效）。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("user_")

        assert result.is_valid
        assert result.normalized == "user_"

    def test_validate_error_details(self):
        """测试验证错误详情。"""
        validator = TwitterUsernameValidator()
        result = validator.validate("invalid user!")

        assert not result.is_valid
        assert result.error_code == "INVALID_FORMAT"
        assert result.error_message is not None
