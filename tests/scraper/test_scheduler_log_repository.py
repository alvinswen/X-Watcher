"""调度器执行日志仓库测试。"""

from datetime import datetime, timedelta, timezone

import pytest

from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog
from src.scraper.infrastructure.scheduler_log_models import SchedulerExecutionLogOrm
from src.scraper.infrastructure.scheduler_log_repository import (
    SchedulerExecutionLogRepository,
)


@pytest.mark.asyncio
class TestSchedulerExecutionLogRepository:
    """异步仓库测试。"""

    async def _insert_log(self, session, **kwargs) -> SchedulerExecutionLogOrm:
        """辅助方法：向数据库直接插入一条日志记录。"""
        defaults = {
            "job_id": "scraper_job",
            "event_type": "executed",
            "executed_at": datetime.now(timezone.utc),
        }
        defaults.update(kwargs)
        orm = SchedulerExecutionLogOrm(**defaults)
        session.add(orm)
        await session.flush()
        return orm

    async def test_get_recent_logs_empty(self, async_session):
        """空表应返回空列表。"""
        repo = SchedulerExecutionLogRepository(async_session)
        logs = await repo.get_recent_logs()
        assert logs == []

    async def test_get_recent_logs_ordering(self, async_session):
        """结果应按 executed_at 降序排列。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(async_session, executed_at=now - timedelta(hours=2))
        await self._insert_log(async_session, executed_at=now - timedelta(hours=1))
        await self._insert_log(async_session, executed_at=now)

        repo = SchedulerExecutionLogRepository(async_session)
        logs = await repo.get_recent_logs()

        assert len(logs) == 3
        # 最新的在前
        assert logs[0].executed_at >= logs[1].executed_at >= logs[2].executed_at

    async def test_filter_by_event_type(self, async_session):
        """应能按事件类型过滤。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(async_session, event_type="executed", executed_at=now)
        await self._insert_log(
            async_session,
            event_type="error",
            executed_at=now,
            error_type="ValueError",
            error_message="test",
        )
        await self._insert_log(async_session, event_type="missed", executed_at=now)

        repo = SchedulerExecutionLogRepository(async_session)

        error_logs = await repo.get_recent_logs(event_type=SchedulerEventType.ERROR)
        assert len(error_logs) == 1
        assert error_logs[0].event_type == SchedulerEventType.ERROR

        executed_logs = await repo.get_recent_logs(
            event_type=SchedulerEventType.EXECUTED
        )
        assert len(executed_logs) == 1

    async def test_filter_by_since(self, async_session):
        """应能按起始时间过滤。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(async_session, executed_at=now - timedelta(days=5))
        await self._insert_log(async_session, executed_at=now - timedelta(days=1))
        await self._insert_log(async_session, executed_at=now)

        repo = SchedulerExecutionLogRepository(async_session)

        # 只查最近 2 天
        logs = await repo.get_recent_logs(since=now - timedelta(days=2))
        assert len(logs) == 2

    async def test_limit_parameter(self, async_session):
        """limit 参数应限制返回数量。"""
        now = datetime.now(timezone.utc)
        for i in range(10):
            await self._insert_log(
                async_session, executed_at=now - timedelta(hours=i)
            )

        repo = SchedulerExecutionLogRepository(async_session)
        logs = await repo.get_recent_logs(limit=3)
        assert len(logs) == 3

    async def test_cleanup_old_logs(self, async_session):
        """应只清理超过保留期的日志。"""
        now = datetime.now(timezone.utc)
        # 插入一条旧日志和一条新日志
        await self._insert_log(async_session, executed_at=now - timedelta(days=60))
        await self._insert_log(async_session, executed_at=now - timedelta(days=1))
        await async_session.commit()

        repo = SchedulerExecutionLogRepository(async_session)
        deleted = await repo.cleanup_old_logs(retention_days=30)
        assert deleted == 1

        # 验证只剩一条
        remaining = await repo.get_recent_logs()
        assert len(remaining) == 1

    async def test_cleanup_preserves_all_when_none_expired(self, async_session):
        """无过期日志时不应删除任何记录。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(async_session, executed_at=now - timedelta(days=1))
        await self._insert_log(async_session, executed_at=now)
        await async_session.commit()

        repo = SchedulerExecutionLogRepository(async_session)
        deleted = await repo.cleanup_old_logs(retention_days=30)
        assert deleted == 0

    async def test_to_domain_conversion(self, async_session):
        """ORM 到领域模型转换应保留所有字段。"""
        now = datetime.now(timezone.utc)
        next_run = now + timedelta(hours=12)
        await self._insert_log(
            async_session,
            event_type="error",
            executed_at=now,
            duration_seconds=3.14,
            error_type="RuntimeError",
            error_message="something failed",
            next_run_time=next_run,
        )

        repo = SchedulerExecutionLogRepository(async_session)
        logs = await repo.get_recent_logs()
        assert len(logs) == 1

        log = logs[0]
        assert log.job_id == "scraper_job"
        assert log.event_type == SchedulerEventType.ERROR
        assert log.duration_seconds == pytest.approx(3.14)
        assert log.error_type == "RuntimeError"
        assert log.error_message == "something failed"
        assert log.id is not None
