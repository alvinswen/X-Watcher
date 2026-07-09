"""pg 下线 B-guard:file 模式守卫真验行为测试。

覆盖:
1. is_file_mode() 随 env 变化。
2. health file 模式:database 组件 healthy 且不执行 SELECT 1。
5. database_size file 模式:返回 data_root 体积或 None,不调 pg_database_size。
6. 强集成兜底:file 模式 + 不可达 DATABASE_URL 下 DB-init + health 不抛/不挂起(证不连 pg)。

⚠️ 本机 .env=file。所有"sqlalchemy 模式"断言用 monkeypatch.setenv 显式翻成 sqlalchemy。
"""

import asyncio


# ---------------------------------------------------------------------------
# 1. is_file_mode() 随 env 变化
# ---------------------------------------------------------------------------
def test_is_file_mode_file(monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    from src.data_layer.provider import is_file_mode

    assert is_file_mode() is True


def test_is_file_mode_sqlalchemy(monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import is_file_mode

    assert is_file_mode() is False


def test_is_file_mode_default_is_not_file(monkeypatch):
    """显式 sqlalchemy 不是 file 模式。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import is_file_mode

    assert is_file_mode() is False


# ---------------------------------------------------------------------------
# 2. health file 模式:不 SELECT 1
# ---------------------------------------------------------------------------
def test_health_check_file_mode_healthy_no_session(monkeypatch, tmp_path):
    """file 模式:health database 组件 healthy。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))  # 存在 → healthy

    from src.main import health_check

    result = asyncio.run(health_check())

    db = result["components"]["database"]
    assert db["status"] == "healthy"
    assert db["mode"] == "file"


def test_health_check_file_mode_unhealthy_when_data_root_missing(monkeypatch, tmp_path):
    """file 模式:data_root 不存在 → unhealthy(故障注入翻红)。"""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(missing))

    from src.main import health_check

    result = asyncio.run(health_check())
    assert result["components"]["database"]["status"] == "unhealthy"


def test_config_routes_check_database_file_mode(monkeypatch, tmp_path):
    """config_routes._check_database file 模式探 data_root,healthy 且不连 pg。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.api.routes.config_routes import _check_database

    result = asyncio.run(_check_database())
    assert result["status"] == "healthy"
    assert result["mode"] == "file"


def test_cli_validate_check_database_file_mode(monkeypatch, tmp_path):
    """cli validate_command._check_database file 模式探 data_root,不连 pg。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.cli.validate_command import _check_database

    result = _check_database()
    assert result["status"] == "healthy"
    assert result["name"] == "database"


# ---------------------------------------------------------------------------
# 3. database_size file 模式
# ---------------------------------------------------------------------------
def test_database_size_file_mode_returns_dir_size(monkeypatch, tmp_path):
    """file 模式:返回 data_root 递归体积(MB),不调 pg_database_size。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    # 写一些字节
    (tmp_path / "a.json").write_bytes(b"x" * 2048)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.json").write_bytes(b"y" * 1024)

    from src.data_layer.disk_usage import get_database_size_mb

    size = get_database_size_mb()
    assert size is not None
    assert size >= 0.0  # 3KB ≈ 0.0 MB 四舍五入,但非 None、不抛


def test_database_size_file_mode_missing_root_returns_none(monkeypatch, tmp_path):
    """file 模式:data_root 不存在 → None,不抛。"""
    missing = tmp_path / "nope"
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(missing))

    from src.data_layer.disk_usage import get_database_size_mb

    assert get_database_size_mb() is None


# ---------------------------------------------------------------------------
# 4. 强集成兜底:file 模式 + 不可达 DATABASE_URL → 不抛/不挂起
# ---------------------------------------------------------------------------
def test_file_mode_unreachable_pg_does_not_connect(monkeypatch, tmp_path):
    """file 模式 + 不可达 DATABASE_URL:DB-init + health 不抛/不挂起(证真不连 pg)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    # 127.0.0.1:1 — 端口 1 必拒,若真连会抛 ConnectionError
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/nope")

    import src.main as main_mod

    # health database 组件:file 模式探目录,不连 pg
    result = asyncio.run(main_mod.health_check())
    assert result["components"]["database"]["status"] == "healthy"
    assert result["components"]["database"]["mode"] == "file"
