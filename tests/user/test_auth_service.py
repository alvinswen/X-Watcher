"""AuthService 认证原语服务单元测试。"""

import os
import re

import pytest

from src.config import clear_settings_cache
from src.user.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def set_jwt_secret():
    """设置测试用 JWT 密钥。"""
    original = os.environ.get("JWT_SECRET_KEY")
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-unit-tests"
    clear_settings_cache()
    yield
    if original is None:
        os.environ.pop("JWT_SECRET_KEY", None)
    else:
        os.environ["JWT_SECRET_KEY"] = original
    clear_settings_cache()


@pytest.fixture
def auth_service():
    return AuthService()


@pytest.mark.asyncio
async def test_hash_and_verify_password(auth_service):
    """测试正常密码的哈希和验证。"""
    password = "MySecurePass123"
    hashed = await auth_service.hash_password(password)

    assert isinstance(hashed, str)
    assert hashed != password
    assert await auth_service.verify_password(password, hashed) is True


@pytest.mark.asyncio
async def test_hash_and_verify_long_password(auth_service):
    """>72 字节密码预哈希后仍可正确验证。"""
    long_password = "A" * 100
    assert len(long_password.encode("utf-8")) > 72

    hashed = await auth_service.hash_password(long_password)
    assert isinstance(hashed, str)
    assert await auth_service.verify_password(long_password, hashed) is True


@pytest.mark.asyncio
async def test_wrong_password_fails(auth_service):
    """错误密码验证失败。"""
    password = "CorrectPassword"
    hashed = await auth_service.hash_password(password)

    assert await auth_service.verify_password("WrongPassword", hashed) is False


def test_generate_api_key_format(auth_service):
    """API Key 以 sna_ 为前缀，总长度 36 字符。"""
    raw_key, key_hash, key_prefix = auth_service.generate_api_key()

    assert raw_key.startswith("sna_")
    # sna_ (4) + 32 hex chars = 36
    assert len(raw_key) == 36
    assert key_prefix == raw_key[:8]
    assert isinstance(key_hash, str)


def test_api_key_hash_sha256(auth_service):
    """API Key 哈希输出为 64 字符十六进制。"""
    raw_key, key_hash, _ = auth_service.generate_api_key()

    assert len(key_hash) == 64
    assert re.match(r"^[0-9a-f]{64}$", key_hash)


def test_verify_api_key_hash(auth_service):
    """正确 API Key 哈希比较。"""
    raw_key, key_hash, _ = auth_service.generate_api_key()

    assert auth_service.verify_api_key_hash(raw_key, key_hash) is True


def test_verify_api_key_hash_wrong(auth_service):
    """错误 API Key 哈希比较。"""
    raw_key, key_hash, _ = auth_service.generate_api_key()

    assert auth_service.verify_api_key_hash("sna_wrong_key_here_1234567890", key_hash) is False


def test_jwt_create_and_decode(auth_service):
    """JWT Token 生成和解码包含正确字段。"""
    token = auth_service.create_jwt_token(user_id=42, email="test@example.com", is_admin=False)

    assert isinstance(token, str)

    payload = auth_service.decode_jwt_token(token)
    assert payload["sub"] == "42"
    assert payload["email"] == "test@example.com"
    assert payload["is_admin"] is False
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_expired(auth_service):
    """过期 JWT Token 抛出 ExpiredSignatureError。"""
    import jwt as pyjwt
    from datetime import datetime, timezone, timedelta

    settings_secret = "test-jwt-secret-key-for-unit-tests"
    expired_payload = {
        "sub": "1",
        "email": "test@example.com",
        "is_admin": False,
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
    }
    expired_token = pyjwt.encode(expired_payload, settings_secret, algorithm="HS256")

    with pytest.raises(pyjwt.ExpiredSignatureError):
        auth_service.decode_jwt_token(expired_token)


def test_temp_password_format(auth_service):
    """临时密码为 12 字符，仅包含字母和数字。"""
    password = auth_service.generate_temp_password()

    assert len(password) == 12
    assert password.isalnum()
