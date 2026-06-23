"""Pytest 配置文件。

提供测试 Fixtures 和配置。
"""

import logging
import os
import tempfile
from logging.handlers import QueueHandler
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config import clear_settings_cache, get_settings
from src.logging_config import shutdown_logging
from src.database.models import Base, reset_engine
from src.database.async_session import reset_async_engine
from src.main import app


# ── 测试环境日志隔离 ──────────────────────────────────────────
# src.main 在 import 时调用 setup_logging()，会创建 QueueHandler + QueueListener
# 写入 logs/x-watcher.log。在测试中不需要文件写入，停止 listener 并移除 handler。
def _remove_file_handlers() -> None:
    shutdown_logging()  # 停止 QueueListener，关闭底层 RotatingFileHandler
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, QueueHandler):
            root.removeHandler(handler)


_remove_file_handlers()

# 导入所有 ORM 模型以确保它们被注册到 Base.metadata
# 这些导入不会在代码中使用，但确保 SQLAlchemy 能够找到所有表
from src.scraper.infrastructure.models import TweetOrm  # noqa: F401
from src.scraper.infrastructure.fetch_stats_models import FetchStatsOrm  # noqa: F401
from src.scraper.infrastructure.scheduler_log_models import SchedulerExecutionLogOrm  # noqa: F401
from src.scraper.infrastructure.article_models import ArticleOrm  # noqa: F401
from src.summarization.infrastructure.models import SummaryOrm  # noqa: F401
from src.topic.infrastructure.models import TopicOrm, TopicAccountOrm, TopicSummaryTaskOrm, TopicSummaryOrm  # noqa: F401

# 在测试开始时加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# ⚠️ 测试套件默认钉 sqlalchemy 模式,中和本机 gitignored .env 的 XWATCHER_DATA_LAYER=file 污染。
# .env 经 load_dotenv 灌入 os.environ;pg 下线接线后(analytics/browse/preference/scraper/...)
# route/MCP/集成测试若未显式钉模式,会在 file 模式下走文件层 data_migrated 而非测试种的 sqlite/内存库
# → 漂移失败(本机无前缀跑出现、CI/干净检出 sqlalchemy 默认则不出现)。统一在此钉 sqlalchemy 基线
# 使套件 env-无关;file 模式测试自行 monkeypatch.setenv("XWATCHER_DATA_LAYER","file") opt-in(覆盖
# 本默认 + 测试后还原)。注:运行全套 file 模式非受支持场景(各测试假设 sqlalchemy ORM patch/种子)。
os.environ["XWATCHER_DATA_LAYER"] = "sqlalchemy"


# 全局同步测试引擎 - 所有通过 get_engine() 获取引擎的代码路径都将被重定向到此处
_sync_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
Base.metadata.create_all(bind=_sync_test_engine)


# 全局异步测试引擎 - 所有通过 get_async_engine()/get_async_session_maker() 的代码路径
# 都将被重定向到此处,杜绝任何测试经异步路径碰真实 pg(DATABASE_URL)。
# ⚠️ 建表需事件循环,而本模块级 + autouse fixture 是同步上下文 → 用"同步 sqlite 连接预建表
# + 异步引擎读同一文件"避开 loop。用 file-based sqlite(而非 :memory:),因 :memory: 跨连接
# 不共享、且异步建表要 loop;file 共享 + 同步预建表最稳。
_async_test_db_path = tempfile.mktemp(suffix="-conftest-async-test.sqlite")
_async_table_creator = create_engine(f"sqlite:///{_async_test_db_path}")
Base.metadata.create_all(bind=_async_table_creator)  # 同步建表,无需 loop
_async_table_creator.dispose()
_async_test_engine = create_async_engine(f"sqlite+aiosqlite:///{_async_test_db_path}")
_async_test_maker = async_sessionmaker(
    _async_test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(autouse=True)
def _isolate_database_singletons():
    """隔离数据库单例，防止测试泄漏写入生产数据库。

    通过 patch get_engine() 使所有同步数据库操作（TaskRegistry._persist_task、
    SchedulerExecutionLogSyncWriter.write_log、get_active_follows_from_db 等）
    使用内存测试数据库而非生产 news_agent.db。

    同时 patch get_async_engine()/get_async_session_maker() 使所有异步数据库代码路径
    (route/MCP/集成测试在默认 sqlalchemy 模式下的 get_async_session_maker() 调用)使用
    隔离的 sqlite 异步引擎,而非连接真实 pg(DATABASE_URL)。镜像同步引擎的隔离方式。

    同时在测试前后重置引擎单例，确保测试之间完全隔离。
    """
    # 重置单例，防止上一个测试的引擎被复用
    reset_engine()
    reset_async_engine()

    # Patch get_engine 使所有 lazy import(函数内 import)路径都返回测试引擎。
    # ⚠️ src.main 在模块级 `from src.database.models import get_engine as engine` 绑定了原函数
    # 引用(import 时定型),patch 源模块的 get_engine 覆盖不到该绑定名 → main.py 的 lifespan
    # 启动期 _init_db_if_needed() 会用未被 patch 的真实 pg sync engine 对真实 pg create_all
    # 重建表。故必须额外 patch src.main.engine 这一绑定名,堵住该同步路径的 pg 泄漏。
    with patch("src.database.models.get_engine", return_value=_sync_test_engine), \
         patch("src.main.engine", return_value=_sync_test_engine), \
         patch("src.database.async_session.get_async_engine", return_value=_async_test_engine), \
         patch("src.database.async_session.get_async_session_maker", return_value=_async_test_maker):
        yield

    # 测试后再次重置单例
    reset_engine()
    reset_async_engine()


@pytest.fixture(autouse=True)
def reset_env_before_each_test():
    """在每个测试前重置环境变量。

    这确保测试不依赖本地 .env 文件中的值。
    但保留 .env 中加载的 API 密钥用于集成测试。
    """
    # 保存原始环境变量（包括从 .env 加载的）
    original_env = os.environ.copy()

    yield

    # 恢复原始环境变量
    os.environ.clear()
    os.environ.update(original_env)
    clear_settings_cache()


# 测试数据库引擎 - 使用 SQLite 内存模式（用于 db_session fixture）
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)

# 创建测试会话工厂
TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


@pytest.fixture(scope="function")
def db_session():
    """数据库会话 Fixture。

    每个测试函数使用独立的内存数据库。
    """
    # 创建所有表
    Base.metadata.create_all(bind=test_engine)

    # 创建会话
    session = TestSessionLocal()

    try:
        yield session
    finally:
        session.close()
        # 清理：删除所有表
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session):  # noqa: ARG001 - 保留参数以确 fixture 顺序
    """FastAPI 测试客户端 Fixture。

    使用测试数据库会话。
    """
    # 清除配置缓存，使用测试环境变量
    clear_settings_cache()

    with TestClient(app) as test_client:
        yield test_client

    # 清除配置缓存
    clear_settings_cache()


@pytest.fixture(scope="function")
def test_settings():
    """测试配置 Fixture。

    提供测试用的配置值。
    """
    # 清除缓存
    clear_settings_cache()

    # 设置测试环境变量
    import os

    test_env = {
        "MINIMAX_API_KEY": "test-api-key",
        "MINIMAX_BASE_URL": "https://api.test.com",
        "TWITTER_API_KEY": "test-twitter-key",
        "TWITTER_BEARER_TOKEN": "test-bearer-token",
        "DATABASE_URL": "sqlite:///:memory:",
        "LOG_LEVEL": "WARNING",  # 测试时减少日志输出
    }

    # 保存原始环境变量
    original_env = {}
    for key, value in test_env.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value

    # 清除缓存以加载新配置
    clear_settings_cache()

    yield get_settings()

    # 恢复原始环境变量
    for key, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value

    # 清除缓存
    clear_settings_cache()


@pytest.fixture(scope="function")
def temp_file():
    """临时文件 Fixture。

    创建一个临时文件，测试后自动删除。
    """
    fd, path = tempfile.mkstemp()
    import os

    try:
        yield Path(path)
    finally:
        os.close(fd)
        os.unlink(path)


@pytest.fixture(scope="function")
def temp_dir():
    """临时目录 Fixture。

    创建一个临时目录，测试后自动删除。
    """
    path = tempfile.mkdtemp()
    import shutil

    try:
        yield Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="function")
def clean_registry():
    """清理任务注册表 Fixture。"""
    from src.scraper import TaskRegistry

    registry = TaskRegistry.get_instance()
    registry.clear_all()
    yield
    registry.clear_all()


@pytest.fixture(scope="function")
async def _test_db_engine():
    """内部 fixture：创建共享的测试数据库引擎。

    每个测试函数使用独立的内存数据库。
    async_session 和 test_session_factory 共享同一个引擎。
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # 创建所有表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine

    # 清理
    await test_engine.dispose()


@pytest.fixture(scope="function")
async def async_session(_test_db_engine):
    """异步数据库会话 Fixture。

    每个测试函数使用独立的内存数据库。
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    test_session_maker = async_sessionmaker(
        _test_db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_session_maker() as session:
        yield session


@pytest.fixture(scope="function")
async def test_session_factory(_test_db_engine):
    """异步会话工厂 Fixture。

    返回 async_sessionmaker 实例，适用于需要 session_factory 的测试
    （如 SummarizationService 的新接口）。
    与 async_session 共享同一个内存数据库引擎。
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(
        _test_db_engine, class_=AsyncSession, expire_on_commit=False
    )

    yield factory


@pytest.fixture(scope="function")
async def async_client(async_session):
    """异步 HTTP 客户端 Fixture（带管理员认证）。

    使用 httpx.AsyncClient 测试 FastAPI 应用。
    自动注入管理员认证，适用于需要认证的 API 端点。
    """
    from httpx import AsyncClient, ASGITransport
    from src.database.async_session import get_db_session
    from src.user.api.auth import get_current_admin_user, get_current_user
    from src.user.domain.models import BOOTSTRAP_ADMIN

    # 使用 ASGI 传输
    transport = ASGITransport(app=app)

    # 覆写依赖注入，返回测试会话
    async def override_get_db_session():
        yield async_session

    async def override_get_current_admin_user():
        return BOOTSTRAP_ADMIN

    async def override_get_current_user():
        return BOOTSTRAP_ADMIN

    # 使用 FastAPI 的 app.dependency_overrides
    original_db_override = app.dependency_overrides.get(get_db_session)
    original_admin_override = app.dependency_overrides.get(get_current_admin_user)
    original_user_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        # 恢复原始依赖
        if original_db_override:
            app.dependency_overrides[get_db_session] = original_db_override
        else:
            app.dependency_overrides.pop(get_db_session, None)
        if original_admin_override:
            app.dependency_overrides[get_current_admin_user] = original_admin_override
        else:
            app.dependency_overrides.pop(get_current_admin_user, None)
        if original_user_override:
            app.dependency_overrides[get_current_user] = original_user_override
        else:
            app.dependency_overrides.pop(get_current_user, None)
