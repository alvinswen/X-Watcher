#!/usr/bin/env python
"""管理员密码工具函数。

供 CLI init 复用的密码生成与哈希工具。
"""

import secrets
import string

from src.user.services.auth_service import _hash_password

__all__ = ["_generate_temp_password", "_hash_password"]


def _generate_temp_password() -> str:
    """生成随机临时密码（12 字符，字母+数字）。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))
