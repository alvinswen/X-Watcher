"""scheduled_job.get_active_follows_async 走文件层。
路径可证:种子只进文件层,返回即证读文件层。"""
from unittest.mock import AsyncMock, patch

import pytest

from src.preference.infrastructure.file_follow_repository import FileFollowStore


async def _seed(tmp_path):
    store = FileFollowStore(tmp_path)
    await store.create_scraper_follow("amy", "r", "admin")
    await store.create_scraper_follow("zoe", "r", "admin")
    await store.update_scraper_follow("zoe", is_active=False)        # inactive → 不入 active
    await store.update_scraper_follow("amy", manual_limit=7)         # manual_limit 透传
    await store.create_scraper_follow("bob", "r", "admin")           # active 且默认 backfill_status=pending


@pytest.mark.asyncio
async def test_get_active_follows_async_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed(tmp_path)
    from src.scraper.scheduled_job import get_active_follows_async

    rows = await get_active_follows_async()
    by_user = {r["username"]: r["manual_limit"] for r in rows}
    assert "zoe" not in by_user            # inactive 不在 active
    assert by_user["amy"] == 7             # manual_limit 透传
    assert by_user["bob"] is None


@pytest.mark.asyncio
async def test_tc_build_382_manual_limit_lookup_failure_is_fail_soft(caplog):
    """TC-BUILD-382: 仓储查询失败返回空映射并留 warning。"""
    from src.scraper.scheduled_job import resolve_manual_limits

    with (
        patch(
            "src.data_layer.provider.get_follows_repo",
            side_effect=RuntimeError("repo unavailable"),
        ),
        caplog.at_level("WARNING", logger="src.scraper.scheduled_job"),
    ):
        result = await resolve_manual_limits(["alice"])

    assert result == {}
    assert "repo unavailable" in caplog.text
    assert "返回空列表" in caplog.text


@pytest.mark.asyncio
async def test_tc_build_387_zero_manual_limit_is_omitted():
    """TC-BUILD-387: manual_limit=0 表示清除手动限额。"""
    from src.scraper.scheduled_job import resolve_manual_limits

    follows = AsyncMock(
        return_value=[
            {"username": "alice", "manual_limit": 0},
            {"username": "bob", "manual_limit": 7},
        ]
    )
    with patch(
        "src.scraper.scheduled_job.get_active_follows_async", new=follows
    ):
        result = await resolve_manual_limits(["alice", "bob"])

    assert result == {"bob": 7}


@pytest.mark.asyncio
async def test_tc_build_388_manual_limits_filter_username_and_positive_value():
    """TC-BUILD-388: 结果只含请求范围内已配置的账号。"""
    from src.scraper.scheduled_job import resolve_manual_limits

    follows = AsyncMock(
        return_value=[
            {"username": "alice", "manual_limit": 3},
            {"username": "bob", "manual_limit": None},
            {"username": "charlie", "manual_limit": 8},
        ]
    )
    with patch(
        "src.scraper.scheduled_job.get_active_follows_async", new=follows
    ):
        result = await resolve_manual_limits(["alice", "bob"])

    assert result == {"alice": 3}


@pytest.mark.asyncio
async def test_tc_build_389_empty_follows_returns_empty_mapping():
    """TC-BUILD-389: 空关注列表返回空映射而不抛错。"""
    from src.scraper.scheduled_job import resolve_manual_limits

    follows = AsyncMock(return_value=[])
    with patch(
        "src.scraper.scheduled_job.get_active_follows_async", new=follows
    ):
        result = await resolve_manual_limits(["alice"])

    assert result == {}
