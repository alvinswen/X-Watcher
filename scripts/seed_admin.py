#!/usr/bin/env python
"""种子数据脚本。

插入默认管理员账户到数据库，设置初始密码。
"""

import base64
import hashlib
import secrets
import string

import bcrypt
from sqlalchemy.orm import Session

from src.database.models import User, get_engine


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


def seed_admin_user() -> None:
    """插入默认管理员账户。

    默认管理员：
    - Email: xi.sun@metalight.ai
    - Name: System Administrator
    - is_admin: True
    """
    engine = get_engine()

    with Session(engine) as session:
        # 检查是否已存在管理员
        existing_admin = session.query(User).filter_by(email="xi.sun@metalight.ai").first()

        if existing_admin:
            print(f"管理员账户已存在: {existing_admin.email}")
            # 确保是管理员
            if not existing_admin.is_admin:
                existing_admin.is_admin = True
                session.commit()
                print("已将现有账户设置为管理员")
            # 如果没有密码，设置初始密码
            if not existing_admin.password_hash:
                temp_password = _generate_temp_password()
                existing_admin.password_hash = _hash_password(temp_password)
                session.commit()
                print(f"已设置初始密码: {temp_password}")
            return

        # 生成临时密码
        temp_password = _generate_temp_password()
        password_hash = _hash_password(temp_password)

        # 创建新的管理员账户
        admin_user = User(
            name="System Administrator",
            email="xi.sun@metalight.ai",
            is_admin=True,
            password_hash=password_hash,
        )

        session.add(admin_user)
        session.commit()

        print("默认管理员账户已创建:")
        print(f"  Email: {admin_user.email}")
        print(f"  Name: {admin_user.name}")
        print(f"  is_admin: {admin_user.is_admin}")
        print(f"  临时密码: {temp_password}")
        print("  请登录后立即修改密码！")


if __name__ == "__main__":
    seed_admin_user()
