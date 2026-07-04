"""MCP Action Guard 安全加固回归测试。"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp import security


def _clear_guard_cache() -> None:
    security._guard_cache.clear()


@pytest.fixture(autouse=True)
def clear_guard_env(monkeypatch):
    """隔离每个测试的 Action Guard 环境变量与进程级缓存。"""
    for key in (
        "MCP_FOLLOWS_ALLOWED_ACTIONS",
        "MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS",
        "MCP_TRIGGER_BACKFILL_ALLOWED_ACTIONS",
        "MCP_SCRAPE_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    _clear_guard_cache()
    yield
    _clear_guard_cache()


def _decode(result: str) -> dict:
    return json.loads(result)


def test_trigger_scrape_guard_restores_allow_after_unset(monkeypatch):
    """TC-MCP-252: trigger_scrape 未配放行，收紧拒绝，撤配恢复放行。"""
    assert security.check_action_guard("trigger_scrape", "scrape") is None

    monkeypatch.setenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", "noop")
    _clear_guard_cache()
    denied = security.check_action_guard("trigger_scrape", "scrape")
    assert denied is not None
    data = _decode(denied)
    assert data["success"] is False
    assert data["error_type"] == "permission"
    assert "trigger_scrape.scrape" in data["error"]

    monkeypatch.delenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", raising=False)
    _clear_guard_cache()
    assert security.check_action_guard("trigger_scrape", "scrape") is None


def test_trigger_backfill_guard_restores_allow_after_unset(monkeypatch):
    """TC-MCP-253: trigger_backfill 未配放行，收紧拒绝，撤配恢复放行。"""
    assert security.check_action_guard("trigger_backfill", "scrape") is None

    monkeypatch.setenv("MCP_TRIGGER_BACKFILL_ALLOWED_ACTIONS", "noop")
    _clear_guard_cache()
    denied = security.check_action_guard("trigger_backfill", "scrape")
    assert denied is not None
    data = _decode(denied)
    assert data["success"] is False
    assert data["error_type"] == "permission"
    assert "trigger_backfill.scrape" in data["error"]

    monkeypatch.delenv("MCP_TRIGGER_BACKFILL_ALLOWED_ACTIONS", raising=False)
    _clear_guard_cache()
    assert security.check_action_guard("trigger_backfill", "scrape") is None


def test_scrape_guard_and_action_guard_are_independent(monkeypatch):
    """TC-MCP-254: 门 1 与门 2 并存，任一拒绝即拒绝。"""
    monkeypatch.setenv("MCP_SCRAPE_ENABLED", "false")
    assert security.check_scrape_guard() is not None

    monkeypatch.setenv("MCP_SCRAPE_ENABLED", "true")
    monkeypatch.setenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", "noop")
    _clear_guard_cache()
    assert security.check_scrape_guard() is None
    denied = security.check_action_guard("trigger_scrape", "scrape")
    assert denied is not None
    assert _decode(denied)["error_type"] == "permission"


def test_independent_env_vars_can_block_backfill_only(monkeypatch):
    """TC-MCP-255: 两个独立 env 变量可禁 backfill 保 scrape。"""
    monkeypatch.setenv("MCP_TRIGGER_BACKFILL_ALLOWED_ACTIONS", "noop")
    _clear_guard_cache()

    assert security.check_action_guard("trigger_scrape", "scrape") is None
    denied = security.check_action_guard("trigger_backfill", "scrape")
    assert denied is not None
    assert _decode(denied)["error_type"] == "permission"


@pytest.mark.asyncio
async def test_trigger_scrape_tool_uses_action_guard(monkeypatch):
    """TC-MCP-256/259: trigger_scrape 工具入口接入门 2 并返回 permission 定位。"""
    from src.mcp.server import create_mcp_server

    monkeypatch.setenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", "noop")
    _clear_guard_cache()
    tool = create_mcp_server()._tool_manager._tools["trigger_scrape"].fn

    with (
        patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
        patch("src.mcp.tools.admin_tools.resolve_user_list", new=AsyncMock()) as resolve_user_list,
    ):
        result = await tool(usernames="alice", limit=1)

    resolve_user_list.assert_not_called()
    data = _decode(result)
    assert data["success"] is False
    assert data["error_type"] == "permission"
    assert "trigger_scrape.scrape" in data["error"]


def test_manage_follows_guard_behavior_unchanged(monkeypatch):
    """TC-MCP-257: 新增两个键不影响 manage_follows 既有 Guard 行为。"""
    assert security.check_action_guard("manage_follows", "list") is None

    monkeypatch.setenv("MCP_FOLLOWS_ALLOWED_ACTIONS", "list,update")
    _clear_guard_cache()
    assert security.check_action_guard("manage_follows", "list") is None
    denied = security.check_action_guard("manage_follows", "deactivate")
    assert denied is not None
    assert _decode(denied)["error_type"] == "permission"


def test_trigger_scrape_allowlist_permits_scrape(monkeypatch):
    """TC-MCP-258: 白名单包含 scrape 时放行。"""
    monkeypatch.setenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", "scrape")
    _clear_guard_cache()
    assert security.check_action_guard("trigger_scrape", "scrape") is None


def test_guard_cache_requires_clear_after_env_change(monkeypatch):
    """TC-MCP-260: 不清缓存会读到旧环境，证明测试必须 clear。"""
    assert security.check_action_guard("trigger_scrape", "scrape") is None
    assert security._guard_cache["trigger_scrape"] is None

    monkeypatch.setenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", "noop")
    assert security.check_action_guard("trigger_scrape", "scrape") is None

    _clear_guard_cache()
    denied = security.check_action_guard("trigger_scrape", "scrape")
    assert denied is not None
    assert _decode(denied)["error_type"] == "permission"
