"""Pytest 配置文件。

提供测试 Fixtures 和配置。
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import clear_settings_cache, get_settings
from src.database.models import Base
from src.main import app

# 导入所有 ORM 模型以确保它们被注册到 Base.metadata
# 这些导入不会在代码中使用，但确保 SQLAlchemy 能够找到所有表
from src.scraper.infrastructure.models import TweetOrm, DeduplicationGroupOrm  # noqa: F401
from src.scraper.infrastructure.fetch_stats_models import FetchStatsOrm  # noqa: F401
from src.summarization.infrastructure.models import SummaryOrm  # noqa: F401

# 在测试开始时加载 .env 文件
from dotenv import load_dotenv
load_dotenv()


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


# 测试数据库引擎 - 使用 SQLite 内存模式
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
async def async_session():
    """异步数据库会话 Fixture。

    每个测试函数使用独立的内存数据库。
    """
    # 创建测试引擎
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # 创建所有表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 创建会话工厂
    test_session_maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_session_maker() as session:
        yield session

    # 清理
    await test_engine.dispose()


@pytest.fixture(scope="function")
async def async_client(async_session):
    """异步 HTTP 客户端 Fixture。

    使用 httpx.AsyncClient 测试 FastAPI 应用。
    """
    from httpx import AsyncClient, ASGITransport
    from src.database.async_session import get_db_session

    # 使用 ASGI 传输
    transport = ASGITransport(app=app)

    # 覆写依赖注入，返回测试会话
    async def override_get_db_session():
        yield async_session

    # 使用 FastAPI 的 app.dependency_overrides
    original_override = app.dependency_overrides.get(get_db_session)
    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        # 恢复原始依赖
        if original_override:
            app.dependency_overrides[get_db_session] = original_override
        else:
            app.dependency_overrides.pop(get_db_session, None)
