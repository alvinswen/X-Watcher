"""聚类 Repository 测试。"""

import pytest
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.infrastructure.models import ClusterAssignmentOrm, ClusteringRunOrm
from src.analytics.infrastructure.repository import ClusteringRepository


class TestClusteringRepository:
    """测试 ClusteringRepository。"""

    async def test_create_and_get_run(self, async_session: AsyncSession):
        """创建并查询聚类运行。"""
        repo = ClusteringRepository()

        run = ClusteringRunOrm(
            status="pending",
            min_tweets_threshold=20,
            linkage_method="average",
        )
        created = await repo.create_run(async_session, run)
        assert created.id is not None

        fetched = await repo.get_run(async_session, created.id)
        assert fetched is not None
        assert fetched.status == "pending"
        assert fetched.min_tweets_threshold == 20

    async def test_list_runs_ordered(self, async_session: AsyncSession):
        """列出运行记录应按创建时间倒序。"""
        repo = ClusteringRepository()

        run1 = ClusteringRunOrm(status="completed", min_tweets_threshold=20, linkage_method="average")
        run2 = ClusteringRunOrm(status="completed", min_tweets_threshold=10, linkage_method="average")

        await repo.create_run(async_session, run1)
        await repo.create_run(async_session, run2)
        await async_session.flush()

        runs = await repo.list_runs(async_session)
        assert len(runs) == 2
        # 最新的在前
        assert runs[0].id >= runs[1].id

    async def test_get_latest_completed(self, async_session: AsyncSession):
        """获取最新完成的运行。"""
        repo = ClusteringRepository()

        run1 = ClusteringRunOrm(
            status="completed",
            min_tweets_threshold=20,
            linkage_method="average",
            completed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        run2 = ClusteringRunOrm(
            status="completed",
            min_tweets_threshold=20,
            linkage_method="average",
            completed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        run3 = ClusteringRunOrm(status="failed", min_tweets_threshold=20, linkage_method="average")

        await repo.create_run(async_session, run1)
        await repo.create_run(async_session, run2)
        await repo.create_run(async_session, run3)
        await async_session.flush()

        latest = await repo.get_latest_completed(async_session)
        assert latest is not None
        assert latest.id == run2.id

    async def test_delete_run_cascades(self, async_session: AsyncSession):
        """删除运行应级联删除分配记录。"""
        repo = ClusteringRepository()

        run = ClusteringRunOrm(status="completed", min_tweets_threshold=20, linkage_method="average")
        run = await repo.create_run(async_session, run)

        assignment = ClusterAssignmentOrm(
            run_id=run.id,
            username="test_user",
            cluster_id=0,
            hourly_distribution_json="[0.04]*24",
            tweet_count=30,
            is_manual_override=False,
        )
        async_session.add(assignment)
        await async_session.flush()

        result = await repo.delete_run(async_session, run.id)
        assert result is True

        fetched = await repo.get_run(async_session, run.id)
        assert fetched is None

    async def test_get_assignment(self, async_session: AsyncSession):
        """查询分配记录。"""
        repo = ClusteringRepository()

        run = ClusteringRunOrm(status="completed", min_tweets_threshold=20, linkage_method="average")
        run = await repo.create_run(async_session, run)

        assignment = ClusterAssignmentOrm(
            run_id=run.id,
            username="some_user",
            cluster_id=1,
            hourly_distribution_json="[0.04]*24",
            tweet_count=25,
            is_manual_override=False,
        )
        async_session.add(assignment)
        await async_session.flush()

        fetched = await repo.get_assignment(async_session, run.id, "some_user")
        assert fetched is not None
        assert fetched.cluster_id == 1
        assert fetched.tweet_count == 25

        # 不存在的用户名
        missing = await repo.get_assignment(async_session, run.id, "nonexistent")
        assert missing is None

    async def test_bulk_create_assignments(self, async_session: AsyncSession):
        """批量创建分配记录。"""
        repo = ClusteringRepository()

        run = ClusteringRunOrm(status="completed", min_tweets_threshold=20, linkage_method="average")
        run = await repo.create_run(async_session, run)

        assignments = [
            ClusterAssignmentOrm(
                run_id=run.id,
                username=f"user_{i}",
                cluster_id=i % 2,
                hourly_distribution_json="[]",
                tweet_count=30,
                is_manual_override=False,
            )
            for i in range(5)
        ]

        await repo.bulk_create_assignments(async_session, assignments)

        # 重新加载运行
        fetched = await repo.get_run(async_session, run.id)
        assert fetched is not None
        assert len(fetched.assignments) == 5
