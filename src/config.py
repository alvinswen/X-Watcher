"""配置管理模块。

使用 Pydantic 加载和验证环境变量。
"""

from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 加载 .env 文件
load_dotenv()


class Settings(BaseSettings):
    """应用配置。

    从环境变量加载配置，使用 Pydantic 进行验证。
    """

    # MiniMax API 配置
    minimax_api_key: str = Field(..., description="MiniMax API 密钥")
    minimax_base_url: str = Field(
        default="https://api.minimaxi.com",
        description="MiniMax API 地址"
    )

    # X 平台 API 配置
    twitter_api_key: str = Field(..., description="X 平台 API 密钥")

    # 数据库配置
    database_url: str = Field(
        default="sqlite:///./news_agent.db",
        description="数据库连接地址"
    )

    # 日志配置
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="日志级别",
        validate_default=True,  # 确保默认值也经过验证
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """验证并标准化日志级别。"""
        if isinstance(v, str):
            return v.upper()
        return v


# 全局缓存，用于测试时清除
_settings_cache: Settings | None = None


def get_settings() -> Settings:
    """获取配置单例。

    使用全局缓存确保配置只加载一次。

    Returns:
        Settings: 配置实例
    """
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
    return _settings_cache


def clear_settings_cache() -> None:
    """清除配置缓存。

    主要用于测试场景。
    """
    global _settings_cache
    _settings_cache = None
