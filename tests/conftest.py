"""Pytest 配置文件。

提供测试 Fixtures 和配置。
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import clear_settings_cache, get_settings
from src.database.models import Base
from src.main import app


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
