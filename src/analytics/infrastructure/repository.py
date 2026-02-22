"""聚类分析数据访问层。"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.analytics.infrastructure.models import ClusterAssignmentOrm, ClusteringRunOrm


class ClusteringRepository:
    """聚类运行数据访问层。"""

    async def create_run(self, session: AsyncSession, run: ClusteringRunOrm) -> ClusteringRunOrm:
        session.add(run)
        await session.flush()
        return run

    async def get_run(self, session: AsyncSession, run_id: int) -> ClusteringRunOrm | None:
        stmt = (
            select(ClusteringRunOrm)
            .options(selectinload(ClusteringRunOrm.assignments))
            .where(ClusteringRunOrm.id == run_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_runs(self, session: AsyncSession) -> list[ClusteringRunOrm]:
        stmt = (
            select(ClusteringRunOrm)
            .order_by(ClusteringRunOrm.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_completed(self, session: AsyncSession) -> ClusteringRunOrm | None:
        stmt = (
            select(ClusteringRunOrm)
            .options(selectinload(ClusteringRunOrm.assignments))
            .where(ClusteringRunOrm.status == "completed")
            .order_by(ClusteringRunOrm.completed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_run(self, session: AsyncSession, run: ClusteringRunOrm) -> ClusteringRunOrm:
        await session.flush()
        return run

    async def delete_run(self, session: AsyncSession, run_id: int) -> bool:
        run = await self.get_run(session, run_id)
        if not run:
            return False
        await session.delete(run)
        await session.flush()
        return True

    async def get_assignment(
        self, session: AsyncSession, run_id: int, username: str
    ) -> ClusterAssignmentOrm | None:
        stmt = select(ClusterAssignmentOrm).where(
            ClusterAssignmentOrm.run_id == run_id,
            ClusterAssignmentOrm.username == username,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_assignments_for_run(self, session: AsyncSession, run_id: int) -> None:
        await session.execute(
            delete(ClusterAssignmentOrm).where(ClusterAssignmentOrm.run_id == run_id)
        )

    async def bulk_create_assignments(
        self, session: AsyncSession, assignments: list[ClusterAssignmentOrm]
    ) -> None:
        for a in assignments:
            session.add(a)
        await session.flush()
