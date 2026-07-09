"""Pytest 配置文件。

提供测试 Fixtures 和配置。

⚠️ 测试基座 = file 模式（CHG-021 起 · 与生产一致）：
- 全局钉 XWATCHER_DATA_LAYER=file，中和本机 gitignored .env 的污染
  （沿 sqlalchemy 时代同款"本机挂 CI 绿"历史事故防御，只是钉的值换成 file）；
- 全局钉一次性临时数据目录 XWATCHER_DATA_ROOT，堵死"未显式设 data_root 的测试
  误读写生产数据目录（data_migrated）"的全部路径；需要数据隔离的测试仍自行
  monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path)) opt-in 覆盖（覆盖 + 测试后还原）。
"""

import logging
import os
import tempfile
from logging.handlers import QueueHandler
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import clear_settings_cache, get_settings
from src.logging_config import shutdown_logging

os.environ.setdefault("TWITTER_API_KEY", "test-twitter-key")
os.environ.setdefault("TWITTER_BEARER_TOKEN", "test-bearer-token")
os.environ["XWATCHER_DATA_LAYER"] = "file"
# 全局一次性临时数据目录：所有未显式 opt-in 覆盖 XWATCHER_DATA_ROOT 的测试都落在这里，
# 杜绝任何测试路径读写真实生产数据目录（data_migrated）。
_session_data_root = tempfile.mkdtemp(prefix="xwatcher-conftest-data-")
os.environ["XWATCHER_DATA_ROOT"] = _session_data_root
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-with-at-least-32-chars"
clear_settings_cache()

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

# 在测试开始时加载 .env 文件
from dotenv import load_dotenv

load_dotenv()

# ⚠️ load_dotenv（默认不覆盖已有 env）后再显式钉一次，双保险：
# 测试套件必须 env-无关（本机 .env 有无、值为何均不改变测试行为）。
os.environ["XWATCHER_DATA_LAYER"] = "file"
os.environ["XWATCHER_DATA_ROOT"] = _session_data_root
clear_settings_cache()


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


@pytest.fixture(scope="function")
def client():
    """FastAPI 测试客户端 Fixture。"""
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
async def async_client():
    """异步 HTTP 客户端 Fixture（带管理员认证）。

    使用 httpx.AsyncClient 测试 FastAPI 应用。
    自动注入管理员认证，适用于需要认证的 API 端点。
    """
    from httpx import ASGITransport, AsyncClient

    from src.user.api.auth import get_current_admin_user, get_current_user
    from src.user.domain.models import BOOTSTRAP_ADMIN

    # 使用 ASGI 传输
    transport = ASGITransport(app=app)

    async def override_get_current_admin_user():
        return BOOTSTRAP_ADMIN

    async def override_get_current_user():
        return BOOTSTRAP_ADMIN

    # 使用 FastAPI 的 app.dependency_overrides
    original_admin_override = app.dependency_overrides.get(get_current_admin_user)
    original_user_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        # 恢复原始依赖
        if original_admin_override:
            app.dependency_overrides[get_current_admin_user] = original_admin_override
        else:
            app.dependency_overrides.pop(get_current_admin_user, None)
        if original_user_override:
            app.dependency_overrides[get_current_user] = original_user_override
        else:
            app.dependency_overrides.pop(get_current_user, None)
