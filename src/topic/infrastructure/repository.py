"""主题管理 Repository。"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
)


class TopicRepository:
    """主题数据访问层。"""

    async def create(self, session: AsyncSession, topic: TopicOrm) -> TopicOrm:
        session.add(topic)
        await session.flush()
        return topic

    async def get_by_id(self, session: AsyncSession, topic_id: int) -> TopicOrm | None:
        stmt = select(TopicOrm).options(selectinload(TopicOrm.accounts)).where(TopicOrm.id == topic_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, session: AsyncSession, name: str) -> TopicOrm | None:
        stmt = select(TopicOrm).where(TopicOrm.name == name)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, session: AsyncSession) -> list[tuple[TopicOrm, int]]:
        """列出所有主题及其账号数量，按创建时间倒序。"""
        account_count_subq = (
            select(func.count(TopicAccountOrm.id))
            .where(TopicAccountOrm.topic_id == TopicOrm.id)
            .correlate(TopicOrm)
            .scalar_subquery()
        )
        stmt = (
            select(TopicOrm, account_count_subq.label("account_count"))
            .order_by(TopicOrm.created_at.desc())
        )
        result = await session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def update(self, session: AsyncSession, topic: TopicOrm) -> TopicOrm:
        await session.flush()
        return topic

    async def delete(self, session: AsyncSession, topic_id: int) -> bool:
        """删除主题（级联删除账号、任务、摘要）。"""
        stmt = (
            select(TopicOrm)
            .options(
                selectinload(TopicOrm.accounts),
                selectinload(TopicOrm.summary_tasks).selectinload(TopicSummaryTaskOrm.summary),
            )
            .where(TopicOrm.id == topic_id)
        )
        result = await session.execute(stmt)
        topic = result.scalar_one_or_none()
        if not topic:
            return False
        await session.delete(topic)
        await session.flush()
        return True

    # ── 账号管理 ──

    async def add_account(self, session: AsyncSession, account: TopicAccountOrm) -> TopicAccountOrm:
        session.add(account)
        await session.flush()
        return account

    async def get_account(self, session: AsyncSession, topic_id: int, username: str) -> TopicAccountOrm | None:
        stmt = select(TopicAccountOrm).where(
            TopicAccountOrm.topic_id == topic_id,
            TopicAccountOrm.username == username,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_accounts(self, session: AsyncSession, topic_id: int) -> list[TopicAccountOrm]:
        stmt = select(TopicAccountOrm).where(TopicAccountOrm.topic_id == topic_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def delete_account(self, session: AsyncSession, topic_id: int, username: str) -> bool:
        stmt = delete(TopicAccountOrm).where(
            TopicAccountOrm.topic_id == topic_id,
            TopicAccountOrm.username == username,
        )
        result = await session.execute(stmt)
        return result.rowcount > 0

    async def replace_accounts(self, session: AsyncSession, topic_id: int, accounts: list[TopicAccountOrm]) -> list[TopicAccountOrm]:
        """替换主题的所有账号。"""
        # 删除旧账号
        await session.execute(
            delete(TopicAccountOrm).where(TopicAccountOrm.topic_id == topic_id)
        )
        # 添加新账号
        for account in accounts:
            session.add(account)
        await session.flush()
        return accounts


class TopicSummaryTaskRepository:
    """摘要任务数据访问层。"""

    async def create_task(self, session: AsyncSession, task: TopicSummaryTaskOrm) -> TopicSummaryTaskOrm:
        session.add(task)
        await session.flush()
        return task

    async def get_task(self, session: AsyncSession, task_id: int) -> TopicSummaryTaskOrm | None:
        stmt = (
            select(TopicSummaryTaskOrm)
            .options(
                selectinload(TopicSummaryTaskOrm.summary),
                selectinload(TopicSummaryTaskOrm.topic),
            )
            .where(TopicSummaryTaskOrm.id == task_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_tasks(self, session: AsyncSession, topic_id: int | None = None) -> list[TopicSummaryTaskOrm]:
        stmt = (
            select(TopicSummaryTaskOrm)
            .options(
                selectinload(TopicSummaryTaskOrm.summary),
                selectinload(TopicSummaryTaskOrm.topic),
            )
            .order_by(TopicSummaryTaskOrm.created_at.desc())
        )
        if topic_id is not None:
            stmt = stmt.where(TopicSummaryTaskOrm.topic_id == topic_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_task(self, session: AsyncSession, task: TopicSummaryTaskOrm) -> TopicSummaryTaskOrm:
        await session.flush()
        return task

    async def delete_task(self, session: AsyncSession, task_id: int) -> bool:
        task = await self.get_task(session, task_id)
        if not task:
            return False
        await session.delete(task)
        await session.flush()
        return True

    async def create_summary(self, session: AsyncSession, summary: TopicSummaryOrm) -> TopicSummaryOrm:
        session.add(summary)
        await session.flush()
        return summary

    async def get_summary_by_task(self, session: AsyncSession, task_id: int) -> TopicSummaryOrm | None:
        stmt = select(TopicSummaryOrm).where(TopicSummaryOrm.task_id == task_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
