"""调度器执行历史 API 测试。"""

from datetime import datetime, timedelta, timezone

import pytest

from src.scraper.infrastructure.scheduler_log_models import SchedulerExecutionLogOrm


@pytest.mark.asyncio
class TestSchedulerHistoryAPI:
    """GET /api/admin/scheduler/history 端点测试。"""

    async def _insert_log(self, session, **kwargs):
        """辅助方法：向数据库插入测试日志。"""
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

    async def test_get_history_empty(self, async_client):
        """空表应返回空列表。"""
        response = await async_client.get("/api/admin/scheduler/history")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_history_with_data(self, async_client, async_session):
        """有数据时应返回正确格式的记录。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(
            async_session,
            event_type="executed",
            executed_at=now,
            duration_seconds=1.5,
        )
        await async_session.commit()

        response = await async_client.get("/api/admin/scheduler/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        record = data[0]
        assert record["job_id"] == "scraper_job"
        assert record["event_type"] == "executed"
        assert record["duration_seconds"] == pytest.approx(1.5)
        assert record["error_type"] is None
        assert record["error_message"] is None
        assert "id" in record
        assert "executed_at" in record

    async def test_filter_by_event_type(self, async_client, async_session):
        """event_type 查询参数应过滤结果。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(async_session, event_type="executed", executed_at=now)
        await self._insert_log(
            async_session,
            event_type="error",
            executed_at=now,
            error_type="ValueError",
            error_message="test",
        )
        await async_session.commit()

        response = await async_client.get(
            "/api/admin/scheduler/history", params={"event_type": "error"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "error"

    async def test_limit_parameter(self, async_client, async_session):
        """limit 查询参数应限制返回数量。"""
        now = datetime.now(timezone.utc)
        for i in range(5):
            await self._insert_log(
                async_session, executed_at=now - timedelta(hours=i)
            )
        await async_session.commit()

        response = await async_client.get(
            "/api/admin/scheduler/history", params={"limit": 2}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_since_parameter(self, async_client, async_session):
        """since 查询参数应过滤时间范围。"""
        now = datetime.now(timezone.utc)
        await self._insert_log(
            async_session, executed_at=now - timedelta(days=5)
        )
        await self._insert_log(async_session, executed_at=now)
        await async_session.commit()

        since = (now - timedelta(days=1)).isoformat()
        response = await async_client.get(
            "/api/admin/scheduler/history", params={"since": since}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    async def test_requires_admin_auth(self, async_session):
        """无认证应返回 401。"""
        from httpx import ASGITransport, AsyncClient

        from src.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/api/admin/scheduler/history")
            assert response.status_code == 401
