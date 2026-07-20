"""tests/sync 公共 fixture（CHG-039 · Q4=B 数据根定向加固）。

定向依据（全树实证 @ 903efdd）：test_sync_routes_error_paths.py 的
test_last_admin_demotion_keeps_exact_detail_and_user_state 经 get_user_repo()
真实读写 env 解析的数据根，是全 tests/ 树唯一"无每测试隔离且真写共享会话根"
的测试。目录级 autouse 每测试独立临时根（参照 tests/user setup_env 形态）；
本目录既有 5 个 opt-in setenv 文件在测试体内的自设根会覆盖本 fixture，互不冲突。
"""
import pytest

from src.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _isolate_data_root(tmp_path, monkeypatch):
    """每测试独立数据根：XWATCHER_DATA_ROOT=tmp_path + settings 缓存双侧清理。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    clear_settings_cache()
    yield
    clear_settings_cache()
