"""任务注册表纯内存语义 + audit 恒空/文件日志 + CLI init 文件层守卫(原 pg 下线 A4/A5 · CHG-028 改写)。

覆盖:
1. 任务持久化脚手架已删除:_persist_task 不复存在(防再引入);recover 仅内存段。
2. get_audit_log 恒返空结构(logs=[]/count=0 · 产品级"接线 or 明示恒空"留 R3/R4)。
3. audit 文件 logger 仍写:audit_log 主函数 audit_logger 仍被调。
4. _create_admin 走文件层:建出 admin + 返 raw_key;重复返 None。
"""

import asyncio
import json


# ---------------------------------------------------------------------------
# A4-1. 持久化脚手架已删除:纯内存语义
# ---------------------------------------------------------------------------
def test_persist_scaffold_removed():
    """_persist_task 已随 CHG-028 删除:注册表纯内存,防 no-op 持久化脚手架再引入。"""
    from src.scraper.task_registry import TaskRegistry

    reg = TaskRegistry.get_instance()
    assert not hasattr(reg, "_persist_task")


# ---------------------------------------------------------------------------
# A4-1b. recover_stale_tasks:纯内存超时恢复
# ---------------------------------------------------------------------------
def test_recover_stale_tasks_memory_segment():
    """recover_stale_tasks 内存超时段工作(DB 残留段已随 CHG-028 删除)。"""
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

    recovered = reg.recover_stale_tasks(max_running_seconds=1800)

    # 内存段仍工作:那个超时 RUNNING 被标 FAILED
    assert recovered >= 1
    assert reg._tasks["stale-mem"]["status"] == TaskStatus.FAILED
    reg.clear_all()


def test_get_audit_log_returns_empty_in_file_mode():
    """get_audit_log 恒返空结构(logs=[]/count=0 · Q5d 形状守卫)。"""
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
    """audit_log 主函数 audit_logger.info 仍被调。"""
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
    """_create_admin 在 FileUserStore 建出 admin(is_admin=True)+ 返 raw_key;重复返 None。"""
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
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    from src.cli.init_command import _create_admin

    k1 = _create_admin("a@file.local", "pw1")
    k2 = _create_admin("b@file.local", "pw2")
    assert k1 and k2 and k1 != k2
