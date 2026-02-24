"""x-watcher init 命令实现。

收集配置 → 生成 .env → 初始化数据库 → 创建管理员 → 验证连通性。
"""

import os
import secrets
import string
import sys

import click

from src.summarization.llm.presets import PROVIDER_PRESETS, get_preset


def _generate_password(length: int = 16) -> str:
    """生成随机密码。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_jwt_secret() -> str:
    """生成 JWT 密钥。"""
    return secrets.token_urlsafe(32)


@click.command()
@click.option("--twitter-api-key", default=None, help="TwitterAPI.io API Key")
@click.option(
    "--llm-provider",
    default=None,
    help=f"LLM 提供商 ({', '.join(s for s in PROVIDER_PRESETS if s != 'custom')})",
)
@click.option("--llm-api-key", default=None, help="LLM API Key")
@click.option("--admin-email", default=None, help="管理员邮箱")
@click.option("--admin-password", default=None, help="管理员密码（默认自动生成）")
@click.option("--no-input", is_flag=True, help="非交互模式（缺必填参数则报错）")
@click.option("--skip-db", is_flag=True, help="跳过数据库初始化")
@click.option("--skip-validate", is_flag=True, help="跳过 API Key 验证")
def init(
    twitter_api_key: str | None,
    llm_provider: str | None,
    llm_api_key: str | None,
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

    # LLM Provider
    available_providers = [s for s in PROVIDER_PRESETS if s != "custom"]
    if not llm_provider:
        if no_input:
            click.echo("错误：--no-input 模式下必须提供 --llm-provider", err=True)
            sys.exit(1)
        click.echo(f"\n可用的 LLM 提供商: {', '.join(available_providers)}")
        llm_provider = click.prompt(
            "选择 LLM 提供商",
            type=click.Choice(available_providers, case_sensitive=False),
        )

    llm_provider = llm_provider.lower()
    preset = get_preset(llm_provider)
    if preset is None and llm_provider != "custom":
        click.echo(f"错误：未知的 LLM 提供商 '{llm_provider}'", err=True)
        click.echo(f"可选值: {', '.join(available_providers)}")
        sys.exit(1)

    # LLM API Key
    if not llm_api_key:
        if no_input:
            click.echo("错误：--no-input 模式下必须提供 --llm-api-key", err=True)
            sys.exit(1)
        llm_api_key = click.prompt(f"{llm_provider} API Key")

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
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        jwt_secret=jwt_secret,
    )

    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        if no_input:
            click.echo(f"  .env 已存在，跳过（使用已有文件）")
        else:
            overwrite = click.confirm(f"  .env 已存在，是否覆盖？", default=False)
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
        click.echo(f"  LLM 提供商: {llm_provider}")
        if preset:
            click.echo(f"  默认模型: {preset.default_model}")
            click.echo(f"  Base URL: {preset.base_url}")
    else:
        click.echo("\n跳过验证（--skip-validate）")

    # ---- 5. 完成摘要 ----
    click.echo("\n" + "=" * 40)
    click.echo("初始化完成！")
    click.echo()
    click.echo("配置摘要：")
    click.echo(f"  Twitter API Key: {twitter_api_key[:8]}...")
    click.echo(f"  LLM 提供商: {llm_provider}")
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
    llm_provider: str,
    llm_api_key: str,
    jwt_secret: str,
) -> str:
    """构建 .env 文件内容。"""
    preset = get_preset(llm_provider)
    provider_slug = llm_provider.upper()

    lines = [
        "# X-watcher 配置（由 x-watcher init 生成）",
        "",
        "# LLM 配置",
        f"LLM_PROVIDERS={llm_provider}",
        f"LLM_{provider_slug}_API_KEY={llm_api_key}",
    ]

    if preset and preset.default_model:
        lines.append(f"LLM_{provider_slug}_MODEL={preset.default_model}")

    lines.extend(
        [
            "",
            "# X 平台 API 配置",
            f"TWITTER_API_KEY={twitter_api_key}",
            "TWITTER_BEARER_TOKEN=placeholder",
            "TWITTER_BASE_URL=https://api.twitterapi.io/twitter",
            "",
            "# 抓取器配置",
            "SCRAPER_ENABLED=true",
            "SCRAPER_INTERVAL=43200",
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
            "# 自动摘要",
            "AUTO_SUMMARIZATION_ENABLED=true",
            "AUTO_SUMMARIZATION_BATCH_SIZE=50",
            "",
            "# 监控",
            "PROMETHEUS_ENABLED=true",
        ]
    )

    return "\n".join(lines) + "\n"


def _write_env(path: str, content: str) -> None:
    """写入 .env 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    click.echo(f"  .env 已生成: {path}")


def _init_database() -> None:
    """初始化数据库表。"""
    from src.database.models import Base, get_engine

    engine = get_engine()
    Base.metadata.create_all(engine)


def _create_admin(email: str, password: str) -> str | None:
    """创建管理员用户并生成默认 API Key。

    Returns:
        raw API Key（用户已存在时返回 None）。
    """
    from scripts.seed_admin import _hash_password

    from src.database.models import ApiKey, User, get_engine
    from src.user.services.auth_service import AuthService

    from sqlalchemy.orm import Session

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
