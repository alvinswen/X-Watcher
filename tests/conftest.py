"""Pytest 配置文件。

提供测试 Fixtures 和配置。

⚠️ 测试基座 = 文件层（CHG-021 起 · 与生产一致；CHG-028 起数据层开关已物理删除,无需再钉）：
- 全局钉一次性临时数据目录 XWATCHER_DATA_ROOT，堵死"未显式设 data_root 的测试
  误读写生产数据目录（data_migrated）"的全部路径；需要数据隔离的测试仍自行
  monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path)) opt-in 覆盖（覆盖 + 测试后还原）。
"""

import logging
import os
import tempfile
from logging.handlers import QueueHandler

import dotenv
import pytest
from fastapi.testclient import TestClient

# ══ .env 隔离层（CHG-DSH-003）· 必须早于任何 src.* 导入 ═════════════════════
# 测试基座的承诺：本机 .env 有无、值为何均不改变测试行为（见下方 load_dotenv 段注释）。
# 三条注入路径在此逐个堵死，全部是**进程内**动作，不读 / 不移动 / 不改名 / 不删除 .env：
#   ① src/config.py:14   load_dotenv()       —— import src.config 时执行
#   ② src/config.py:165  env_file=".env"     —— Settings() 实例化时读文件
#   ③ tests/conftest.py:49 load_dotenv()     —— 测试基座自己读（下方已整段删除）
# 已知边界：用户 shell 里导出的同名变量不在本层处理（需求 §4.6-8 / 裁决 Q3）。
os.environ["TWITTER_API_KEY"] = "test-twitter-key"  # 硬钉：setdefault 会被导入期注入抢先


def _load_dotenv_disabled_under_tests(*_args: object, **_kwargs: object) -> bool:
    """隔离期替代 dotenv.load_dotenv：禁止从 .env 向 os.environ 注入任何键。"""
    return False


dotenv.load_dotenv = _load_dotenv_disabled_under_tests  # ①③ 一并关闭

from src.config import Settings, clear_settings_cache, get_settings
from src.logging_config import shutdown_logging

# ② 关掉 pydantic-settings 的 env_file 文件直读：此后 Settings() 只认 os.environ + 代码默认值。
Settings.model_config["env_file"] = None
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

# 本文件**不再**加载 .env：三条注入路径已在文件顶部关闭（CHG-DSH-003）。
# 历史实现在此处 load_dotenv()，与下方「测试套件必须 env-无关」的承诺相反，已删除。

# 隔离层之后（不再有 .env 注入）再显式钉一次，双保险：
# 测试套件必须 env-无关（本机 .env 有无、值为何均不改变测试行为）。
os.environ["XWATCHER_DATA_ROOT"] = _session_data_root
clear_settings_cache()


@pytest.fixture(autouse=True)
def reset_env_before_each_test():
    """在每个测试前重置环境变量。

    这确保测试不依赖本地 .env 文件中的值：进程环境已在导入期与 .env 隔离
    （见文件顶部隔离层），因此本 fixture 抓到的基线是「不含 .env 注入」的干净态。
    """
    # 保存原始环境变量（已与 .env 隔离）
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
        "TWITTER_API_KEY": "test-twitter-key",
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
