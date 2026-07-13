"""scheduled_job.get_active_follows_async 走文件层。
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
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed(tmp_path)
    from src.scraper.scheduled_job import get_active_follows_async

    rows = await get_active_follows_async()
    by_user = {r["username"]: r["manual_limit"] for r in rows}
    assert "zoe" not in by_user            # inactive 不在 active
    assert by_user["amy"] == 7             # manual_limit 透传
    assert by_user["bob"] is None
