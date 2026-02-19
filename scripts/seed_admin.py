#!/usr/bin/env python
"""种子数据脚本。

插入默认管理员账户到数据库，设置初始密码。
支持参数化调用（供 CLI 使用）和独立运行。
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


def create_admin_user(
    email: str = "admin@x-watcher.local",
    name: str = "System Administrator",
    password: str | None = None,
) -> tuple[str, str]:
    """创建或更新管理员账户。

    Args:
        email: 管理员邮箱
        name: 管理员名称
        password: 密码（None 则自动生成）

    Returns:
        tuple[email, password]: 管理员邮箱和密码
    """
    if password is None:
        password = _generate_temp_password()

    engine = get_engine()

    with Session(engine) as session:
        existing_admin = session.query(User).filter_by(email=email).first()

        if existing_admin:
            print(f"管理员账户已存在: {existing_admin.email}")
            if not existing_admin.is_admin:
                existing_admin.is_admin = True
                session.commit()
                print("已将现有账户设置为管理员")
            if not existing_admin.password_hash:
                existing_admin.password_hash = _hash_password(password)
                session.commit()
                print(f"已设置初始密码: {password}")
            return email, password

        admin_user = User(
            name=name,
            email=email,
            is_admin=True,
            password_hash=_hash_password(password),
        )

        session.add(admin_user)
        session.commit()

        print("默认管理员账户已创建:")
        print(f"  Email: {admin_user.email}")
        print(f"  Name: {admin_user.name}")
        print(f"  is_admin: {admin_user.is_admin}")
        print(f"  临时密码: {password}")
        print("  请登录后立即修改密码！")

        return email, password


def seed_admin_user() -> None:
    """插入默认管理员账户（向后兼容接口）。"""
    create_admin_user()


if __name__ == "__main__":
    seed_admin_user()
