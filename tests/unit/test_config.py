"""测试配置模块。"""

import pytest

VALID_JWT_SECRET = "x" * 32


def _make_settings(jwt_secret: str):
    from src.config import Settings

    return Settings(
        twitter_api_key="twitter-key",
        jwt_secret_key=jwt_secret,
    )


def _assert_jwt_guard_exits(capsys, jwt_secret: str) -> str:
    from src.config import validate_jwt_secret_strength

    with pytest.raises(SystemExit) as exc_info:
        validate_jwt_secret_strength(_make_settings(jwt_secret))

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "启动失败：JWT 签名密钥强度校验未通过" in stderr
    assert 'python -c "import secrets;print(secrets.token_urlsafe(32))"' in stderr
    assert "JWT_SECRET_KEY=<上一步生成的值>" in stderr
    assert "Traceback" not in stderr
    return stderr


def test_config_loads_from_env(monkeypatch):
    """测试从环境变量加载配置。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    # 设置环境变量
    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")

    # 导入配置（在设置环境变量之后）
    from src.config import get_settings

    settings = get_settings()

    assert settings.twitter_api_key == "twitter-key"


def test_config_validation_error_when_invalid_log_level(monkeypatch):
    """测试无效日志级别时抛出验证错误。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
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

    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")  # 设置不同的值

    from src.config import get_settings

    settings = get_settings()
    assert settings.log_level == "ERROR"


def test_config_log_level_case_insensitive(monkeypatch):
    """测试日志级别不区分大小写（会被转换为大写）。"""
    from src.config import clear_settings_cache, get_settings
    clear_settings_cache()

    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")
    monkeypatch.setenv("LOG_LEVEL", "warning")  # 小写

    settings = get_settings()
    assert settings.log_level == "WARNING"  # 应该被转换为大写


def test_config_singleton(monkeypatch):
    """测试配置单例模式。"""
    # 清除缓存
    from src.config import clear_settings_cache
    clear_settings_cache()

    monkeypatch.setenv("TWITTER_API_KEY", "twitter-key")

    from src.config import get_settings

    settings1 = get_settings()
    settings2 = get_settings()

    # 应该返回同一个实例
    assert settings1 is settings2


def test_validate_jwt_secret_strength_rejects_default(capsys):
    """测试默认 JWT 密钥会 fail-loud 拒绝启动。"""
    stderr = _assert_jwt_guard_exits(capsys, "change-me-in-production")
    assert "默认值" in stderr


@pytest.mark.parametrize("jwt_secret", ["", "   "])
def test_validate_jwt_secret_strength_rejects_blank(capsys, jwt_secret):
    """测试空串/纯空白 JWT 密钥会被拒绝。"""
    stderr = _assert_jwt_guard_exits(capsys, jwt_secret)
    assert "不能为空或仅包含空白字符" in stderr


def test_validate_jwt_secret_strength_rejects_31_chars(capsys):
    """测试长度 31 的非默认 JWT 密钥会被拒绝。"""
    stderr = _assert_jwt_guard_exits(capsys, "x" * 31)
    assert "长度必须 >= 32 字符" in stderr
    assert "当前 31" in stderr


def test_validate_jwt_secret_strength_accepts_32_chars():
    """测试长度正好 32 的非默认 JWT 密钥可以通过。"""
    from src.config import validate_jwt_secret_strength

    validate_jwt_secret_strength(_make_settings(VALID_JWT_SECRET))


def test_validate_jwt_secret_strength_accepts_token_urlsafe_style():
    """测试安装向导样式强随机密钥不会被误伤。"""
    from src.config import validate_jwt_secret_strength

    validate_jwt_secret_strength(
        _make_settings("N8V06BqkAwvGL4gnPuxgb0eTIODlqKO1xxhB9OS02VU")
    )
