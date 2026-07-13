"""文件层守卫真验行为测试(原 pg 下线 B-guard · CHG-028 幻影开关删除后改写)。

覆盖:
1. health:database 组件探 data_root,healthy/unhealthy 随目录存在性。
2. database_size:返回 data_root 体积或 None。
3. 残留旧 env 惰性兜底:XWATCHER_DATA_LAYER/DATABASE_URL 设任意值均不影响行为
   (开关已物理删除,误设不再静默关守卫)。
"""

import asyncio


# ---------------------------------------------------------------------------
# 1. health:database 组件探 data_root
# ---------------------------------------------------------------------------
def test_health_check_file_mode_healthy_no_session(monkeypatch, tmp_path):
    """health database 组件 healthy(data_root 存在)。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))  # 存在 → healthy

    from src.main import health_check

    result = asyncio.run(health_check())

    db = result["components"]["database"]
    assert db["status"] == "healthy"
    assert db["mode"] == "file"


def test_health_check_file_mode_unhealthy_when_data_root_missing(monkeypatch, tmp_path):
    """data_root 不存在 → unhealthy(故障注入翻红)。"""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(missing))

    from src.main import health_check

    result = asyncio.run(health_check())
    assert result["components"]["database"]["status"] == "unhealthy"


def test_config_routes_check_database_file_mode(monkeypatch, tmp_path):
    """config_routes._check_database 探 data_root,healthy。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.api.routes.config_routes import _check_database

    result = asyncio.run(_check_database())
    assert result["status"] == "healthy"
    assert result["mode"] == "file"


def test_cli_validate_check_database_file_mode(monkeypatch, tmp_path):
    """cli validate_command._check_database 探 data_root。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.cli.validate_command import _check_database

    result = _check_database()
    assert result["status"] == "healthy"
    assert result["name"] == "database"


# ---------------------------------------------------------------------------
# 2. database_size
# ---------------------------------------------------------------------------
def test_database_size_file_mode_returns_dir_size(monkeypatch, tmp_path):
    """返回 data_root 递归体积(MB)。"""
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
    """data_root 不存在 → None,不抛。"""
    missing = tmp_path / "nope"
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(missing))

    from src.data_layer.disk_usage import get_database_size_mb

    assert get_database_size_mb() is None


# ---------------------------------------------------------------------------
# 3. 残留旧 env 惰性兜底(CHG-028:幻影开关物理删除 · 误设不再改变行为)
# ---------------------------------------------------------------------------
def test_stale_legacy_env_is_inert(monkeypatch, tmp_path):
    """残留旧 env(XWATCHER_DATA_LAYER=sqlalchemy + 不可达 DATABASE_URL)完全惰性:
    health 仍 healthy/file,磁盘统计仍工作(原开关误设会静默关守卫,现物理消除)。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    # 旧开关的"毒值"与不可达 DB 地址:均已无任何读取方
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/nope")

    import src.main as main_mod
    from src.data_layer.disk_usage import get_database_size_mb

    result = asyncio.run(main_mod.health_check())
    assert result["components"]["database"]["status"] == "healthy"
    assert result["components"]["database"]["mode"] == "file"
    assert get_database_size_mb() is not None
