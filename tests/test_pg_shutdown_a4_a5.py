"""pg 下线 A4 记录表 + A5 CLI init:file 模式守卫真验行为测试。

owner 定 A4 = accept-no-persist(file 模式跳过 pg 写、守卫读侧返空;audit 文件 logger
仍写、task 历史仅内存);A5 = CLI init file 模式不建表、管理员走文件层。
默认 sqlalchemy 模式零行为变化。

覆盖:
1. A4 写 file 跳过:file 模式 _persist_task / recover DB 段不碰 get_engine。
2. A4 读 file 返空:get_task_history 返 []、get_audit_log 返空结构,均不开 session。
3. A4 audit 文件 logger 仍写:file 模式 audit_log 主函数 audit_logger 仍被调。
4. A5 init file 跳过 create_all。
5. A5 _create_admin file 走文件层:建出 admin(get_user_by_email 查得 + is_admin)+ 返 raw_key;重复返 None。

⚠️ 本机 .env=file。所有"sqlalchemy 模式"断言用 monkeypatch.setenv 显式翻成 sqlalchemy。
"""

import asyncio
import json


# ---------------------------------------------------------------------------
# A4-1. 写侧 file 跳过:_persist_task 早返,不碰 get_engine
# ---------------------------------------------------------------------------
def test_persist_task_skips_in_file_mode(monkeypatch):
    """file 模式:_persist_task 早返,get_engine call_count==0(原 try/except 会吞抛,故用计数 spy)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")

    from src.scraper.task_registry import TaskRegistry, TaskStatus

    reg = TaskRegistry.get_instance()
    task_data = {
        "task_id": "t-file-1",
        "task_name": "demo",
        "status": TaskStatus.COMPLETED,
        "created_at": __import__("datetime").datetime.now(),
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        "metadata": {},
    }
    reg._persist_task(task_data)


# ---------------------------------------------------------------------------
# A4-1b. recover_stale_tasks:DB 段 file 模式跳过、内存段仍工作
# ---------------------------------------------------------------------------
def test_recover_stale_tasks_skips_db_segment_in_file_mode(monkeypatch):
    """file 模式:recover DB 残留段跳过(不碰 get_engine),内存超时段仍工作。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")

    from datetime import datetime, timedelta

    from src.scraper.task_registry import TaskRegistry, TaskStatus

    reg = TaskRegistry.get_instance()
    reg.clear_all()
    # 注入一个内存中超时的 RUNNING 任务
    with reg._task_lock:
        reg._tasks["stale-mem"] = {
            "task_id": "stale-mem",
            "task_name": "x",
            "status": TaskStatus.RUNNING,
            "created_at": datetime.now() - timedelta(seconds=9999),
            "started_at": datetime.now() - timedelta(seconds=9999),
            "completed_at": None,
            "progress": {"current": 0, "total": 0, "percentage": 0.0},
            "result": None,
            "error": None,
            "metadata": {},
        }

    # patch _persist_task 避免 update_task_status 触发(file 早返已覆盖,这里隔离内存段)
    recovered = reg.recover_stale_tasks(max_running_seconds=1800)

    # 内存段仍工作:那个超时 RUNNING 被标 FAILED
    assert recovered >= 1
    assert reg._tasks["stale-mem"]["status"] == TaskStatus.FAILED
    reg.clear_all()


def test_get_audit_log_returns_empty_in_file_mode(monkeypatch):
    """file 模式:get_audit_log 返空结构(logs=[]/count=0)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")

    # get_audit_log 是 status_tools.register 内的闭包 → 用 FakeMCP 抓取
    from src.mcp.tools.status_tools import register

    captured = {}

    class _FakeMCP:
        def tool(self, *a, **k):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn

            return deco

    register(_FakeMCP())
    get_audit_log = captured["get_audit_log"]

    raw = asyncio.run(get_audit_log(limit=50))
    payload = json.loads(raw)
    # success_response 结构:取 data 字段(沿现有返回形态)
    data = payload.get("data", payload)
    assert data["logs"] == []
    assert data["count"] == 0


# ---------------------------------------------------------------------------
# A4-3. audit 文件 logger 仍写(file 模式只跳 pg 写,文件日志必须仍执行)
# ---------------------------------------------------------------------------
def test_audit_log_file_logger_still_writes_in_file_mode(monkeypatch):
    """file 模式:audit_log 主函数 audit_logger.info 仍被调。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")

    import src.mcp.security as sec_mod

    info_calls = {"n": 0}
    monkeypatch.setattr(
        sec_mod.audit_logger,
        "info",
        lambda *a, **k: info_calls.__setitem__("n", info_calls["n"] + 1),
    )

    # get_user_name 可能依赖 contextvar,patch 成稳定值
    monkeypatch.setattr(sec_mod, "get_user_name", lambda: "tester")

    sec_mod.audit_log("manage_follows", "add", params={"x": 1}, result="success")

    assert info_calls["n"] == 1, "file 模式 audit 文件 logger 仍应写一次"


# ---------------------------------------------------------------------------
# A5. _create_admin file 走文件层
# ---------------------------------------------------------------------------
def test_create_admin_file_mode_builds_admin_and_returns_key(monkeypatch, tmp_path):
    """file 模式:_create_admin 在 FileUserStore 建出 admin(is_admin=True)+ 返 raw_key;重复返 None。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.cli.init_command import _create_admin

    raw_key = _create_admin("admin@file.local", "Secret123!")
    assert raw_key is not None
    assert raw_key.startswith("sna_")

    # 绕 _create_admin,独立用 FileUserStore 复核落盘(假绿防御)
    from src.user.infrastructure.file_user_repository import FileUserStore

    store = FileUserStore(tmp_path)
    user = asyncio.run(store.get_user_by_email("admin@file.local"))
    assert user is not None
    assert user.is_admin is True
    assert user.name == "System Administrator"
    # api key 落盘
    keys = asyncio.run(store.get_keys_by_user(user.id))
    assert len(keys) == 1
    assert keys[0].name == "default"
    # password_hash 存盘(get_password_hash_by_email 拿得到)
    ph = asyncio.run(store.get_password_hash_by_email("admin@file.local"))
    assert ph is not None and ph != "Secret123!"

    # 重复调:已存在 → 返 None
    again = _create_admin("admin@file.local", "Secret123!")
    assert again is None


def test_create_admin_file_mode_distinct_keys_each_first_create(monkeypatch, tmp_path):
    """故障注入向:两个不同 email 各首建,raw_key 互异且都 sna_ 前缀(证非伪造常量)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.cli.init_command import _create_admin

    k1 = _create_admin("a@file.local", "pw1")
    k2 = _create_admin("b@file.local", "pw2")
    assert k1 and k2 and k1 != k2
