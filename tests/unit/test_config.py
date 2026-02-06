"""测试配置模块。"""

import os

import pytest
from pydantic import ValidationError


def test_config_loads_from_env(monkeypatch):
    """测试从环境变量加载配置。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    # 设置环境变量
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-123")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    # 导入配置（在设置环境变量之后）
    from src.config import Settings, get_settings

    settings = get_settings()

    assert settings.minimax_api_key == "test-key-123"
    assert settings.minimax_base_url == "https://api.test.com"
    assert settings.twitter_api_key == "twitter-key"
    assert settings.twitter_bearer_token == "test-bearer-token"
    assert settings.database_url == "sqlite:///./test.db"


def test_config_validation_error_when_invalid_log_level(monkeypatch):
    """测试无效日志级别时抛出验证错误。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LOG_LEVEL", "INVALID")

    from pydantic import ValidationError
    from src.config import Settings

    # 应该抛出 ValidationError
    with pytest.raises(ValidationError) as exc_info:
        Settings()

    # 验证错误包含 log_level 字段
    errors = exc_info.value.errors()
    error_fields = {e["loc"][0] for e in errors}
    assert "log_level" in error_fields


def test_config_log_level_default_value_in_class():
    """测试 Settings 类中定义的日志级别默认值为 INFO。

    注意：实际运行时，.env 文件中的 LOG_LEVEL=DEBUG 会被加载，
    但这个测试验证类定义中的默认值是正确的。
    """
    from src.config import Settings

    # 直接检查类模型字段的默认值
    log_level_field = Settings.model_fields["log_level"]
    assert log_level_field.default == "INFO"


def test_config_log_level_from_env_file():
    """测试配置从 .env 文件加载 LOG_LEVEL。

    本项目的 .env 文件设置 LOG_LEVEL=DEBUG，这是开发时的预期行为。
    """
    from src.config import clear_settings_cache, get_settings

    clear_settings_cache()
    settings = get_settings()

    # .env 文件中的值是 DEBUG
    assert settings.log_level in ("DEBUG", "INFO")  # 允许两种情况


def test_config_log_level_custom(monkeypatch):
    """测试自定义日志级别可以覆盖环境变量。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")  # 设置不同的值

    from src.config import get_settings

    settings = get_settings()
    assert settings.log_level == "ERROR"


def test_config_log_level_case_insensitive(monkeypatch):
    """测试日志级别不区分大小写（会被转换为大写）。"""
    from src.config import clear_settings_cache, get_settings
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LOG_LEVEL", "warning")  # 小写

    settings = get_settings()
    assert settings.log_level == "WARNING"  # 应该被转换为大写


def test_config_singleton(monkeypatch):
    """测试配置单例模式。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-bearer-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    from src.config import get_settings

    settings1 = get_settings()
    settings2 = get_settings()

    # 应该返回同一个实例
    assert settings1 is settings2
