"""CHG-040 MCP 手动 limit 边界与配置载荷契约。"""

import json
from unittest.mock import patch

import pytest


def _manage_follows_tool():
    from src.mcp.server import create_mcp_server

    return create_mcp_server()._tool_manager._tools["manage_follows"].fn


async def _seed_follow(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.config import clear_settings_cache
    from src.preference.infrastructure.file_follow_repository import FileFollowStore

    clear_settings_cache()
    store = FileFollowStore(tmp_path)
    await store.create_scraper_follow("alice", "reason", "test")
    return store


async def _update(tool, **kwargs):
    with (
        patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
        patch("src.mcp.security.check_action_guard", return_value=None),
    ):
        return json.loads(await tool(action="update", username="alice", **kwargs))


@pytest.mark.asyncio
async def test_manual_limit_negative_rejected(monkeypatch, tmp_path):
    store = await _seed_follow(monkeypatch, tmp_path)

    result = await _update(_manage_follows_tool(), manual_limit=-1)

    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert "0-1000" in result["error"]
    assert (await store.get_follow_by_username("alice")).manual_limit is None


@pytest.mark.asyncio
async def test_manual_limit_over_max_rejected(monkeypatch, tmp_path):
    store = await _seed_follow(monkeypatch, tmp_path)

    result = await _update(_manage_follows_tool(), manual_limit=1001)

    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert "0-1000" in result["error"]
    assert (await store.get_follow_by_username("alice")).manual_limit is None


@pytest.mark.asyncio
async def test_manual_limit_zero_clears(monkeypatch, tmp_path):
    store = await _seed_follow(monkeypatch, tmp_path)
    await store.update_scraper_follow("alice", manual_limit=7)

    result = await _update(_manage_follows_tool(), manual_limit=0)

    assert result["success"] is True
    assert (await store.get_follow_by_username("alice")).manual_limit is None


@pytest.mark.asyncio
async def test_manual_limit_bounds_and_none(monkeypatch, tmp_path):
    store = await _seed_follow(monkeypatch, tmp_path)
    tool = _manage_follows_tool()

    assert (await _update(tool, manual_limit=1))["success"] is True
    assert (await store.get_follow_by_username("alice")).manual_limit == 1
    assert (await _update(tool, manual_limit=1000))["success"] is True
    assert (await store.get_follow_by_username("alice")).manual_limit == 1000
    assert (await _update(tool, reason="changed", manual_limit=None))["success"] is True
    follow = await store.get_follow_by_username("alice")
    assert follow.manual_limit == 1000
    assert follow.reason == "changed"


@pytest.mark.asyncio
async def test_config_payload_keys(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_PAGES_PER_SCRAPE", "10")
    from src.config import clear_settings_cache
    from src.mcp.server import create_mcp_server

    clear_settings_cache()
    mcp = create_mcp_server()
    resources = mcp._resource_manager._resources
    assert set(resources) == {
        "xwatcher://status",
        "xwatcher://follows",
        "xwatcher://config",
        "xwatcher://recipes/daily-summary",
        "xwatcher://recipes/claude-code-summarize",
    }
    payload = json.loads(await resources["xwatcher://config"].read())
    assert payload["scraper"]["max_pages_per_scrape"] == 10
    assert "max_" + "extra_pages" not in payload["scraper"]
