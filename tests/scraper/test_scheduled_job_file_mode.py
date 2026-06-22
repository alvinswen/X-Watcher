"""scheduled_job 在 XWATCHER_DATA_LAYER=file 下走文件层(同步桥 + async 变体)。
路径可证:种子只进文件层,返回即证读文件层。"""
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
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed(tmp_path)
    from src.scraper.scheduled_job import get_active_follows_async

    rows = await get_active_follows_async()
    by_user = {r["username"]: r["manual_limit"] for r in rows}
    assert "zoe" not in by_user            # inactive 不在 active
    assert by_user["amy"] == 7             # manual_limit 透传
    assert by_user["bob"] is None


@pytest.mark.asyncio
async def test_get_pending_backfill_async_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed(tmp_path)
    from src.scraper.scheduled_job import get_pending_backfill_users_async

    pending = await get_pending_backfill_users_async()
    assert set(pending) == {"amy", "bob"}   # active+pending;zoe inactive 排除


def test_sync_bridge_file_mode_no_running_loop(monkeypatch, tmp_path):
    """同步桥在无 running loop 时(后台线程模型)经 asyncio.run 正常返回。"""
    import asyncio

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    asyncio.run(_seed(tmp_path))
    from src.scraper.scheduled_job import (
        get_active_follows_from_db,
        get_pending_backfill_users_from_db,
    )

    rows = get_active_follows_from_db()
    assert {r["username"] for r in rows} == {"amy", "bob"}
    assert set(get_pending_backfill_users_from_db()) == {"amy", "bob"}
