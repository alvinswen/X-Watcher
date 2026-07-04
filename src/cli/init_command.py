"""x-watcher init 命令实现。

收集配置 → 生成 .env → 初始化数据库 → 创建管理员 → 验证连通性。
"""

import os
import secrets
import string
import sys

import click


def _generate_password(length: int = 16) -> str:
    """生成随机密码。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_jwt_secret() -> str:
    """生成 JWT 密钥。"""
    return secrets.token_urlsafe(32)


@click.command()
@click.option("--twitter-api-key", default=None, help="TwitterAPI.io API Key")
@click.option("--admin-email", default=None, help="管理员邮箱")
@click.option("--admin-password", default=None, help="管理员密码（默认自动生成）")
@click.option("--no-input", is_flag=True, help="非交互模式（缺必填参数则报错）")
@click.option("--skip-db", is_flag=True, help="跳过数据库初始化")
@click.option("--skip-validate", is_flag=True, help="跳过 API Key 验证")
def init(
    twitter_api_key: str | None,
    admin_email: str | None,
    admin_password: str | None,
    no_input: bool,
    skip_db: bool,
    skip_validate: bool,
) -> None:
    """初始化 X-watcher 项目配置。

    交互式引导或通过 CLI 参数一键完成：.env 生成、数据库初始化、管理员创建。
    """
    click.echo("X-watcher 初始化向导")
    click.echo("=" * 40)

    # ---- 1. 收集配置 ----

    # Twitter API Key
    if not twitter_api_key:
        if no_input:
            click.echo("错误：--no-input 模式下必须提供 --twitter-api-key", err=True)
            sys.exit(1)
        twitter_api_key = click.prompt("Twitter API Key (TwitterAPI.io)")

    # Admin email
    if not admin_email:
        if no_input:
            admin_email = "admin@x-watcher.local"
        else:
            admin_email = click.prompt("管理员邮箱", default="admin@x-watcher.local")

    # Admin password
    generated_password = False
    if not admin_password:
        admin_password = _generate_password()
        generated_password = True

    # JWT secret
    jwt_secret = _generate_jwt_secret()

    # ---- 2. 生成 .env ----
    click.echo("\n生成 .env 文件...")

    env_content = _build_env_content(
        twitter_api_key=twitter_api_key,
        jwt_secret=jwt_secret,
    )

    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        if no_input:
            click.echo("  .env 已存在，跳过（使用已有文件）")
        else:
            overwrite = click.confirm("  .env 已存在，是否覆盖？", default=False)
            if not overwrite:
                click.echo("  跳过 .env 生成")
            else:
                _write_env(env_path, env_content)
    else:
        _write_env(env_path, env_content)

    # ---- 3. 数据库初始化 ----
    raw_api_key = None
    if not skip_db:
        click.echo("\n初始化数据库...")
        try:
            _init_database()
            click.echo("  数据库初始化完成")
        except Exception as e:
            click.echo(f"  数据库初始化失败: {e}", err=True)
            if no_input:
                sys.exit(1)

        # 创建管理员
        click.echo("\n创建管理员账户...")
        try:
            raw_api_key = _create_admin(admin_email, admin_password)
            click.echo(f"  管理员账户已创建: {admin_email}")
        except Exception as e:
            click.echo(f"  创建管理员失败: {e}", err=True)
    else:
        click.echo("\n跳过数据库初始化（--skip-db）")

    # ---- 4. 验证 ----
    if not skip_validate:
        click.echo("\n验证配置...")
        # 简单输出配置摘要即可，详细验证用 x-watcher validate
        click.echo("  可运行 x-watcher validate 检查 Twitter API 与数据库")
    else:
        click.echo("\n跳过验证（--skip-validate）")

    # ---- 5. 完成摘要 ----
    click.echo("\n" + "=" * 40)
    click.echo("初始化完成！")
    click.echo()
    click.echo("配置摘要：")
    click.echo(f"  Twitter API Key: {twitter_api_key[:8]}...")
    click.echo(f"  管理员邮箱: {admin_email}")
    if generated_password:
        click.echo(f"  管理员密码: {admin_password}  (自动生成，请妥善保管)")
    if raw_api_key:
        click.echo(f"  管理员 API Key: {raw_api_key}")
        click.echo("  (此 Key 仅显示一次，请妥善保管！前端界面需要此 Key 认证)")
    click.echo()
    click.echo("下一步：")
    click.echo("  启动服务:  x-watcher serve")
    if raw_api_key:
        click.echo("  前端配置:  打开前端 -> 侧边栏底部 -> 设置 API Key")
    click.echo("  验证配置:  x-watcher validate")
    click.echo("  API 文档:  http://localhost:8000/docs")


def _build_env_content(
    twitter_api_key: str,
    jwt_secret: str,
) -> str:
    """构建 .env 文件内容。"""
    lines = [
        "# X-watcher 配置（由 x-watcher init 生成）",
        "",
        "# X 平台 API 配置",
        f"TWITTER_API_KEY={twitter_api_key}",
        "TWITTER_BEARER_TOKEN=placeholder",
        "TWITTER_BASE_URL=https://api.twitterapi.io/twitter",
        "",
        "# 抓取器配置",
        "SCRAPER_ENABLED=true",
        "SCRAPER_USERNAMES=",
        "SCRAPER_LIMIT=30",
        "",
        "# 数据库配置",
        "DATABASE_URL=sqlite:///./news_agent.db",
        "",
        "# 日志配置",
        "LOG_LEVEL=INFO",
        "",
        "# JWT 认证",
        f"JWT_SECRET_KEY={jwt_secret}",
        "JWT_EXPIRE_HOURS=24",
        "",
        "# 监控",
        "PROMETHEUS_ENABLED=true",
    ]

    return "\n".join(lines) + "\n"


def _write_env(path: str, content: str) -> None:
    """写入 .env 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    click.echo(f"  .env 已生成: {path}")


def _init_database() -> None:
    """初始化数据库表。"""
    from src.data_layer.provider import is_file_mode

    if is_file_mode():
        click.echo("  file 模式:跳过建表(数据层为文件)")
        return
    from src.database.models import Base, get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)


def _create_admin(email: str, password: str) -> str | None:
    """创建管理员用户并生成默认 API Key。

    Returns:
        raw API Key（用户已存在时返回 None）。
    """
    from scripts.seed_admin import _hash_password
    from src.data_layer.provider import is_file_mode
    from src.user.services.auth_service import AuthService

    if is_file_mode():
        return _create_admin_file(email, password, _hash_password, AuthService)

    from sqlalchemy.orm import Session

    from src.database.models import ApiKey, User, get_engine

    engine = get_engine()
    with Session(engine) as session:
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            click.echo(f"  管理员账户已存在: {email}")
            if not existing.is_admin:
                existing.is_admin = True
                session.commit()
                click.echo("  已将现有账户设置为管理员")
            return None

        admin_user = User(
            name="System Administrator",
            email=email,
            is_admin=True,
            password_hash=_hash_password(password),
        )
        session.add(admin_user)
        session.flush()  # 获取 admin_user.id

        # 生成默认 API Key
        auth_svc = AuthService()
        raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
        session.add(ApiKey(
            user_id=admin_user.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name="default",
        ))
        session.commit()
        return raw_key


def _create_admin_file(email, password, hash_password, auth_service_cls) -> str | None:
    """file 模式创建管理员:经 FileUserStore 文件层(async,asyncio.run 桥接)。

    映射 sqlalchemy 分支:存在 → echo + 设 is_admin(经 update_user)返 None;
    不存在 → create_user(password_hash) + update_user(is_admin=True) + 生成默认 API Key 返 raw_key。
    FileUserStore.create_user 仅收 name/email/password_hash(is_admin 硬置 False),
    故 admin 标志经 update_user(is_admin=True) 落盘(UserDomain/盘面均有 is_admin 字段)。

    CLI 同步上下文无 running loop → asyncio.run 安全。
    """
    import asyncio

    from src.data_layer.provider import get_user_repo

    store = get_user_repo()

    async def _run() -> str | None:
        existing = await store.get_user_by_email(email)
        if existing is not None:
            click.echo(f"  管理员账户已存在: {email}")
            if not existing.is_admin:
                await store.update_user(existing.id, is_admin=True)
                click.echo("  已将现有账户设置为管理员")
            return None

        user = await store.create_user(
            name="System Administrator",
            email=email,
            password_hash=hash_password(password),
        )
        await store.update_user(user.id, is_admin=True)

        # 生成默认 API Key
        auth_svc = auth_service_cls()
        raw_key, key_hash, key_prefix = auth_svc.generate_api_key()
        await store.create_api_key(
            user_id=user.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name="default",
        )
        return raw_key

    return asyncio.run(_run())
