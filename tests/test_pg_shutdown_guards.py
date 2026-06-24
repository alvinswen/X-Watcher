"""pg 下线 B-guard:file 模式守卫真验行为测试。

覆盖:
1. is_file_mode() 随 env 变化。
2. DB-init 短路:file 模式 Base.metadata.create_all 不被调用、sqlalchemy 模式调用一次。
3. mcp init_database 短路:file 模式早返,不调 create_all。
4. health file 模式:database 组件 healthy 且不开 session / 不执行 SELECT 1。
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
    """未设 env(默认 sqlalchemy)不是 file 模式。"""
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import is_file_mode

    assert is_file_mode() is False


# ---------------------------------------------------------------------------
# 2. DB-init 短路:_init_db_if_needed()
# ---------------------------------------------------------------------------
def test_init_db_skips_create_all_in_file_mode(monkeypatch, tmp_path):
    """file 模式:_init_db_if_needed 早返,create_all 不被调用(call_count==0)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    import src.main as main_mod

    calls = {"n": 0}
    monkeypatch.setattr(
        main_mod.Base.metadata, "create_all", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    )
    main_mod._init_db_if_needed()

    assert calls["n"] == 0, "file 模式不应调用 create_all"


def test_init_db_calls_create_all_in_sqlalchemy_mode(monkeypatch, tmp_path):
    """sqlalchemy 模式:_init_db_if_needed 调 create_all 恰一次(故障注入会翻红)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/probe.db")

    import src.main as main_mod

    calls = {"n": 0}
    monkeypatch.setattr(
        main_mod.Base.metadata, "create_all", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    )
    main_mod._init_db_if_needed()

    assert calls["n"] == 1, "sqlalchemy 模式应调用 create_all 恰一次"


# ---------------------------------------------------------------------------
# 3. mcp init_database 短路
# ---------------------------------------------------------------------------
def test_mcp_init_database_skips_in_file_mode(monkeypatch):
    """file 模式:init_database 早返,不导入/不调 create_all。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")

    import src.database.models as models_mod

    calls = {"n": 0}
    monkeypatch.setattr(
        models_mod.Base.metadata,
        "create_all",
        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1),
    )

    from src.mcp.lifespan import init_database

    init_database()  # 不应抛、不应建表

    assert calls["n"] == 0, "file 模式 init_database 不应调用 create_all"


# ---------------------------------------------------------------------------
# 4. health file 模式:不开 session / 不 SELECT 1
# ---------------------------------------------------------------------------
def test_health_check_file_mode_healthy_no_session(monkeypatch, tmp_path):
    """file 模式:health database 组件 healthy 且不调 get_async_session_maker。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))  # 存在 → healthy

    import src.database.async_session as async_session_mod

    def _boom(*a, **k):
        raise AssertionError("file 模式不应调用 get_async_session_maker(不连 pg)")

    monkeypatch.setattr(async_session_mod, "get_async_session_maker", _boom)

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

    import src.database.async_session as async_session_mod

    monkeypatch.setattr(
        async_session_mod,
        "get_async_session_maker",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应连 pg")),
    )

    from src.main import health_check

    result = asyncio.run(health_check())
    assert result["components"]["database"]["status"] == "unhealthy"


def test_config_routes_check_database_file_mode(monkeypatch, tmp_path):
    """config_routes._check_database file 模式探 data_root,healthy 且不连 pg。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    import src.database.async_session as async_session_mod

    monkeypatch.setattr(
        async_session_mod,
        "get_async_session_maker",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应连 pg")),
    )

    from src.api.routes.config_routes import _check_database

    result = asyncio.run(_check_database())
    assert result["status"] == "healthy"
    assert result["mode"] == "file"


def test_cli_validate_check_database_file_mode(monkeypatch, tmp_path):
    """cli validate_command._check_database file 模式探 data_root,不连 pg。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    import src.database.models as models_mod

    monkeypatch.setattr(
        models_mod,
        "get_engine",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应连 pg")),
    )

    from src.cli.validate_command import _check_database

    result = _check_database()
    assert result["status"] == "healthy"
    assert result["name"] == "database"


# ---------------------------------------------------------------------------
# 5. database_size file 模式
# ---------------------------------------------------------------------------
def test_database_size_file_mode_returns_dir_size(monkeypatch, tmp_path):
    """file 模式:返回 data_root 递归体积(MB),不调 pg_database_size。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    # 写一些字节
    (tmp_path / "a.json").write_bytes(b"x" * 2048)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.json").write_bytes(b"y" * 1024)

    # spy:确保不进 pg 分支
    import src.database.models as models_mod

    monkeypatch.setattr(
        models_mod,
        "get_engine",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("file 模式不应调 pg get_engine")),
    )

    from src.database.dialect import get_database_size_mb

    size = get_database_size_mb()
    assert size is not None
    assert size >= 0.0  # 3KB ≈ 0.0 MB 四舍五入,但非 None、不抛


def test_database_size_file_mode_missing_root_returns_none(monkeypatch, tmp_path):
    """file 模式:data_root 不存在 → None,不抛。"""
    missing = tmp_path / "nope"
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(missing))

    from src.database.dialect import get_database_size_mb

    assert get_database_size_mb() is None


# ---------------------------------------------------------------------------
# 6. 强集成兜底:file 模式 + 不可达 DATABASE_URL → 不抛/不挂起
# ---------------------------------------------------------------------------
def test_file_mode_unreachable_pg_does_not_connect(monkeypatch, tmp_path):
    """file 模式 + 不可达 DATABASE_URL:DB-init + health 不抛/不挂起(证真不连 pg)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    # 127.0.0.1:1 — 端口 1 必拒,若真连会抛 ConnectionError
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/nope")

    import src.main as main_mod

    # DB-init 段:file 模式应早返,不碰 engine
    main_mod._init_db_if_needed()  # 不抛即证未连 pg

    # health database 组件:file 模式探目录,不连 pg
    result = asyncio.run(main_mod.health_check())
    assert result["components"]["database"]["status"] == "healthy"
    assert result["components"]["database"]["mode"] == "file"


def test_metrics_collection_skipped_in_file_mode(monkeypatch):
    """file 模式:_start_metrics_collection 早返,不启动线程(不访问 engine.pool)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("PROMETHEUS_ENABLED", "true")  # 即便开了 prometheus 也不应启线程

    import src.database.async_session as async_session_mod

    # 重置线程状态
    monkeypatch.setattr(async_session_mod, "_metrics_thread", None)
    monkeypatch.setattr(async_session_mod, "_metrics_running", False)

    # spy Thread 构造,确保 file 模式不创建线程
    import threading

    created = {"n": 0}
    real_thread = threading.Thread

    def _spy_thread(*a, **k):
        created["n"] += 1
        return real_thread(*a, **k)

    monkeypatch.setattr(async_session_mod, "Thread", _spy_thread)

    async_session_mod._start_metrics_collection()

    assert created["n"] == 0, "file 模式不应创建 metrics 线程"
    assert async_session_mod._metrics_running is False
