"""认证原语服务。

提供密码哈希、API Key 生成、JWT Token 管理等认证基础功能。
纯函数式设计，不持有数据库访问权限。
"""

import asyncio
import base64
import hashlib
import hmac
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Any

import bcrypt
import jwt

from src.config import get_settings


class AuthService:
    """认证原语服务 -- 纯函数式设计，不持有数据库访问权限。"""

    async def hash_password(self, password: str) -> str:
        """bcrypt 哈希密码。>72 字节预先 SHA-256+base64 处理。"""
        password_bytes = password.encode("utf-8")
        if len(password_bytes) > 72:
            password_bytes = base64.b64encode(
                hashlib.sha256(password_bytes).digest()
            )
        hashed = await asyncio.to_thread(
            bcrypt.hashpw, password_bytes, bcrypt.gensalt(rounds=12)
        )
        return hashed.decode("utf-8")

    async def verify_password(self, password: str, hashed: str) -> bool:
        """验证密码。"""
        password_bytes = password.encode("utf-8")
        if len(password_bytes) > 72:
            password_bytes = base64.b64encode(
                hashlib.sha256(password_bytes).digest()
            )
        hashed_bytes = hashed.encode("utf-8") if isinstance(hashed, str) else hashed
        return await asyncio.to_thread(
            bcrypt.checkpw, password_bytes, hashed_bytes
        )

    def generate_api_key(self) -> tuple[str, str, str]:
        """生成 API Key。返回 (raw_key, key_hash, key_prefix)。"""
        raw_key = f"sna_{secrets.token_hex(16)}"
        key_hash = self.hash_api_key(raw_key)
        key_prefix = raw_key[:8]
        return raw_key, key_hash, key_prefix

    def hash_api_key(self, raw_key: str) -> str:
        """SHA-256 哈希 API Key。"""
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def verify_api_key_hash(self, raw_key: str, stored_hash: str) -> bool:
        """常量时间比较 API Key 哈希。"""
        computed = self.hash_api_key(raw_key)
        return hmac.compare_digest(computed, stored_hash)

    def create_jwt_token(self, user_id: int, email: str, is_admin: bool) -> str:
        """生成 JWT Access Token。"""
        settings = get_settings()
        payload = {
            "sub": str(user_id),
            "email": email,
            "is_admin": is_admin,
            "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")

    def decode_jwt_token(self, token: str) -> dict[str, Any]:
        """解码并验证 JWT Token。"""
        settings = get_settings()
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=["HS256"]
        )

    def generate_temp_password(self) -> str:
        """生成随机临时密码（12 字符，字母+数字）。"""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(12))
