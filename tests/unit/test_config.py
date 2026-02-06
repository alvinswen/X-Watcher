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
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    # 导入配置（在设置环境变量之后）
    from src.config import Settings, get_settings

    settings = get_settings()

    assert settings.minimax_api_key == "test-key-123"
    assert settings.minimax_base_url == "https://api.test.com"
    assert settings.twitter_api_key == "twitter-key"
    assert settings.database_url == "sqlite:///./test.db"


def test_config_validation_error_when_invalid_log_level(monkeypatch):
    """测试无效日志级别时抛出验证错误。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
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


def test_config_log_level_default(monkeypatch):
    """测试日志级别默认值。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    from src.config import get_settings

    settings = get_settings()
    assert settings.log_level == "INFO"


def test_config_log_level_custom(monkeypatch):
    """测试自定义日志级别。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    from src.config import get_settings

    settings = get_settings()
    assert settings.log_level == "DEBUG"


def test_config_singleton(monkeypatch):
    """测试配置单例模式。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.test.com")
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

    from src.config import get_settings

    settings1 = get_settings()
    settings2 = get_settings()

    # 应该返回同一个实例
    assert settings1 is settings2
