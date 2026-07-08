#!/usr/bin/env python
"""管理员密码工具函数。

供 CLI init 复用的密码生成与哈希工具。
"""

import base64
import hashlib
import secrets
import string

import bcrypt


def _generate_temp_password() -> str:
    """生成随机临时密码（12 字符，字母+数字）。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _hash_password(password: str) -> str:
    """bcrypt 哈希密码。"""
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        password_bytes = base64.b64encode(
            hashlib.sha256(password_bytes).digest()
        )
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")
