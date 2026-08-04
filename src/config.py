"""配置管理模块。

使用 Pydantic 加载和验证环境变量。
"""

import sys
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 加载 .env 文件
load_dotenv()

DEFAULT_JWT_SECRET_KEY = "change-me-in-production"
MIN_JWT_SECRET_LENGTH = 32
JWT_SECRET_GENERATE_COMMAND = (
    'python -c "import secrets;print(secrets.token_urlsafe(32))"'
)


class Settings(BaseSettings):
    """应用配置。

    从环境变量加载配置，使用 Pydantic 进行验证。
    """

    # X 平台 API 配置
    twitter_api_key: str = Field(..., description="X 平台 API 密钥")
    twitter_base_url: str = Field(
        default="https://api.twitterapi.io/twitter", description="TwitterAPI.io 基础地址"
    )

    # 抓取器配置
    scraper_limit: int = Field(default=30, ge=1, le=1000, description="单次抓取推文数量限制")

    # 日志配置
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="日志级别",
        validate_default=True,  # 确保默认值也经过验证
    )
    log_format: Literal["text", "json"] = Field(
        default="text",
        description="控制台日志格式（text=人类可读, json=结构化）",
    )
    log_file: str | None = Field(
        default="logs/x-watcher.log",
        description="日志文件路径，None 或空字符串禁用文件输出",
    )
    log_file_max_bytes: int = Field(
        default=50 * 1024 * 1024,
        description="单个日志文件最大字节数（默认 50MB）",
    )
    log_file_backup_count: int = Field(
        default=5,
        ge=0,
        le=20,
        description="日志文件备份数量",
    )

    # 监控配置
    prometheus_enabled: bool = Field(default=True, description="是否启用 Prometheus 监控")

    # 管理员 API 配置
    admin_api_key: str | None = Field(
        default=None, description="管理员 API Key，用于管理员 API 认证"
    )

    # JWT 认证配置
    jwt_secret_key: str = Field(default=DEFAULT_JWT_SECRET_KEY, description="JWT 签名密钥")
    jwt_expire_hours: int = Field(default=24, description="JWT 过期时间（小时）")

    # Claude Code 翻译/摘要接管模型名（写入 provenance 元数据）
    claude_code_model_name: str = Field(
        default="claude-opus-4-8",
        description="Claude Code 翻译/摘要接管时写入数据库的模型名（model_name / llm_model 字段）",
    )

    # 动态 limit 配置
    scraper_min_limit: int = Field(
        default=5, ge=1, le=100, description="动态 limit 最小值（退避下限）"
    )
    scraper_max_limit: int = Field(
        default=300, ge=100, le=1000, description="动态 limit 最大值（上限保护）"
    )
    scraper_ema_alpha: float = Field(
        default=0.3, ge=0.1, le=0.9, description="EMA 平滑系数，越大越重视近期数据"
    )
    scraper_early_stop_threshold: int = Field(
        default=5, ge=0, le=50, description="连续已存在推文阈值，达到后提前终止（0 禁用）"
    )
    scraper_max_pages_per_scrape: int = Field(
        default=10,
        ge=1,
        le=50,
        description="常规增量抓取单次单账号最大翻页数硬上限（每页至多 20 条，默认 10 页 ≈ 200 条/次）",
    )

    # 按组增量搜索抓取配置
    scraper_incremental_enabled: bool = Field(default=False, description="是否启用按组增量搜索抓取")
    scraper_incremental_cutover_groups: str = Field(
        default="", description="已切换到纯增量路径的组号，逗号分隔"
    )
    scraper_incremental_overlap_minutes: int = Field(
        default=30, ge=0, le=1440, description="增量水位安全回看窗口（分钟）"
    )
    scraper_incremental_max_accounts_per_group: int = Field(
        default=20, ge=1, le=20, description="单个增量查询组的最大账号数"
    )
    scraper_incremental_max_query_chars: int = Field(
        default=450, ge=100, le=450, description="增量查询串安全字符上限（不含上限值）"
    )
    scraper_incremental_clean_rounds_required: int = Field(
        default=7, ge=1, description="逐组切换前要求的连续零漏失轮数"
    )
    scraper_incremental_stalled_rounds_alert: int = Field(
        default=3, ge=1, description="连续失败未推进轮数告警阈值"
    )
    scraper_incremental_sentinels: str = Field(
        default="GaryMarcus,levelsio,elonmusk", description="静默失败判别哨兵账号，逗号分隔"
    )
    scraper_incremental_bridge_tweets: int = Field(
        default=100, ge=0, le=1000, description="初次上线搭桥时每账号抓取条数"
    )
    scraper_incremental_new_account_backfill_tweets: int = Field(
        default=200, ge=0, le=1000, description="新账号首次纳入时每账号补历史条数"
    )
    scraper_incremental_max_pages_per_round: int = Field(
        default=25,
        ge=1,
        le=100,
        description=(
            "增量抓取【每组每轮】最大翻页数硬上限（每页至多 20 条，默认 25 页 ≈ 500 条/组/轮）。"
            "⚠️ 单位是「每组」，与 scraper_max_pages_per_scrape（每账号）语义不同，禁止互相复用"
        ),
    )
    scraper_incremental_resume_rounds_alert: int = Field(
        default=10, ge=1, description="续翻轮数过多时的积压消化缓慢告警阈值"
    )

    # 任务超时配置
    task_max_running_seconds: int = Field(
        default=1800,
        ge=60,
        le=7200,
        description="任务最大运行时长（秒），超时后自动标记为失败。默认 30 分钟",
    )

    # Feed API 配置
    feed_max_tweets: int = Field(
        default=200, ge=1, le=1000, description="Feed API 单次最大返回推文数量"
    )

    # TwitterAPI.io 余额告警阈值（按 recharge_credits 数值，返回推文按 15 credits/条计费）
    twitter_balance_warning_threshold: int = Field(
        default=50000, ge=0, description="余额低于此值时前端显示黄色告警（默认约 12 天用量）"
    )
    twitter_balance_danger_threshold: int = Field(
        default=10000, ge=0, description="余额低于此值时前端显示红色告警（默认约 2.5 天用量）"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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


def _jwt_secret_strength_errors(secret: str | None) -> list[str]:
    """返回 JWT 密钥强度错误列表。"""
    normalized = (secret or "").strip()
    errors: list[str] = []

    if normalized == DEFAULT_JWT_SECRET_KEY:
        errors.append(
            f"JWT_SECRET_KEY 不得使用默认值 {DEFAULT_JWT_SECRET_KEY!r}"
        )
    if not normalized:
        errors.append("JWT_SECRET_KEY 不能为空或仅包含空白字符")
    if len(normalized) < MIN_JWT_SECRET_LENGTH:
        errors.append(
            "JWT_SECRET_KEY 长度必须 >= "
            f"{MIN_JWT_SECRET_LENGTH} 字符（当前 {len(normalized)}）"
        )

    return errors


def validate_jwt_secret_strength(settings: Settings | None = None) -> None:
    """启动期校验 JWT 签名密钥强度，不合规则 fail-loud 退出。"""
    current_settings = settings or get_settings()
    errors = _jwt_secret_strength_errors(current_settings.jwt_secret_key)
    if not errors:
        return

    print(
        "\n".join(
            [
                "启动失败：JWT 签名密钥强度校验未通过。",
                "不满足规则：",
                *[f"- {error}" for error in errors],
                "",
                "生成强随机密钥：",
                f"  {JWT_SECRET_GENERATE_COMMAND}",
                "写入 .env：",
                "  JWT_SECRET_KEY=<上一步生成的值>",
            ]
        ),
        file=sys.stderr,
    )
    sys.exit(1)


def clear_settings_cache() -> None:
    """清除配置缓存。

    主要用于测试场景。
    """
    global _settings_cache
    _settings_cache = None
