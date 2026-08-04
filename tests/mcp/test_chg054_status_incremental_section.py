"""CHG-054 MCP status and trigger wire-contract guards."""

import inspect
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from src.scraper.domain.scrape_group_state import (
    GroupAlert,
    ReconcileOutcome,
    RoundOutcome,
    ScrapeGroupState,
)
from src.scraper.infrastructure.file_scrape_group_state_repository import (
    FileScrapeGroupStateStore,
)


@pytest.mark.asyncio
async def test_status_has_exact_six_top_level_keys_and_incremental_state(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    repo = FileScrapeGroupStateStore(tmp_path)
    await repo.upsert_group(
        ScrapeGroupState(
            group_id="g1",
            usernames=["alice"],
            since_id="200",
            last_path="dual",
            consecutive_clean_rounds=3,
            last_round=RoundOutcome(fetched=2, new=1, duplicate_discarded=1),
            last_reconcile=ReconcileOutcome(extra=1, extra_ids=["201"]),
            alerts=[GroupAlert(kind="example", group_id="g1", advice="inspect")],
        )
    )

    from src.mcp.tools import status_tools

    mcp = FastMCP("test")
    status_tools.register(mcp)
    payload = json.loads(await mcp._tool_manager._tools["get_system_status"].fn())
    data = payload["data"]
    assert set(data) == {
        "tweets",
        "follows",
        "summaries",
        "external_dependencies",
        "system",
        "incremental_scrape",
    }
    section = data["incremental_scrape"]
    assert section["groups"][0]["clean_rounds"] == "3/7"
    assert section["groups"][0]["last_reconcile"]["extra"] == 1
    assert section["alerts"][0]["kind"] == "example"


@pytest.mark.asyncio
async def test_incremental_state_failure_is_fail_soft(monkeypatch):
    from src.data_layer import provider
    from src.mcp.tools import status_tools

    monkeypatch.setattr(provider, "get_scrape_group_state_repo", Mock(side_effect=ValueError("broken state")))
    mcp = FastMCP("test")
    status_tools.register(mcp)
    payload = json.loads(await mcp._tool_manager._tools["get_system_status"].fn())
    assert payload["success"] is True
    section = payload["data"]["incremental_scrape"]
    assert section["groups"] == []
    assert section["alerts"][0]["kind"] == "state_unreadable"


@pytest.mark.asyncio
async def test_trigger_scrape_signature_docstring_and_return_contract():
    from src.mcp.tools import admin_tools

    mcp = FastMCP("test")
    admin_tools.register(mcp)
    fn = mcp._tool_manager._tools["trigger_scrape"].fn
    signature = inspect.signature(fn)
    assert list(signature.parameters) == ["usernames", "limit"]
    assert signature.parameters["usernames"].default is None
    assert signature.parameters["limit"].default == 100
    assert "若账号配置了手动抓取上限（manual_limit），该配置优先于 limit 参数生效。" in inspect.getdoc(fn)
    assert "调用方式不变" in inspect.getdoc(fn)

    service = Mock()
    service.scrape_users = AsyncMock(return_value="task-1")
    service.close = AsyncMock()
    registry = Mock()
    registry.get_tasks_by_status.return_value = []
    with (
        patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
        patch("src.mcp.tools.admin_tools.resolve_user_list", new=AsyncMock(return_value=["alice"])),
        patch("src.scraper.ScrapingService", return_value=service),
        patch("src.scraper.TaskRegistry.get_instance", return_value=registry),
        patch("src.scraper.scheduled_job.resolve_manual_limits", new=AsyncMock(return_value={})),
    ):
        payload = json.loads(await fn("alice", 100))
    assert set(payload["data"]) == {"task_id", "usernames", "limit", "message"}
    service.scrape_users.assert_awaited_once_with(usernames=["alice"], limit=100, manual_limits={})
