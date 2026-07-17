"""Admin 抓取入口的过期任务清理接线回归测试。"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.api.routes import admin
from src.scraper import TaskRegistry, TaskStatus
from src.user.domain.models import BOOTSTRAP_ADMIN


def test_start_scraping_cleans_only_expired_terminal_tasks(monkeypatch) -> None:
    registry = TaskRegistry.get_instance()
    registry.clear_all()

    expired_completed = registry.create_task("expired-completed")
    expired_failed = registry.create_task("expired-failed")
    old_running = registry.create_task("old-running")
    terminal_without_time = registry.create_task("terminal-without-time")

    registry.update_task_status(expired_completed, TaskStatus.COMPLETED)
    registry.update_task_status(expired_failed, TaskStatus.FAILED, error="expected")
    registry.update_task_status(old_running, TaskStatus.RUNNING)
    registry.update_task_status(terminal_without_time, TaskStatus.COMPLETED)

    old_time = datetime.now() - timedelta(hours=25)
    registry._tasks[expired_completed]["completed_at"] = old_time
    registry._tasks[expired_failed]["completed_at"] = old_time
    registry._tasks[old_running]["completed_at"] = old_time
    registry._tasks[terminal_without_time]["completed_at"] = None

    def close_background(coroutine, *, name):  # noqa: ANN001, ARG001
        coroutine.close()
        return MagicMock()

    monkeypatch.setattr(admin.asyncio, "create_task", close_background)

    try:
        response = asyncio.run(
            admin.start_scraping(
                admin.ScrapeRequest(usernames="newuser", limit=1),
                _admin=BOOTSTRAP_ADMIN,
            )
        )

        assert response.status == "pending"
        assert registry.get_task_status(expired_completed) is None
        assert registry.get_task_status(expired_failed) is None
        assert registry.get_task_status(old_running) is not None
        assert registry.get_task_status(terminal_without_time) is not None
    finally:
        registry.clear_all()
