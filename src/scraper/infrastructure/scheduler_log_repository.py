"""调度器执行日志仓库。

提供同步写入（供 APScheduler 回调线程使用）和异步查询（供 API 使用）两种操作模式。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog
from src.scraper.infrastructure.scheduler_log_models import SchedulerExecutionLogOrm

logger = logging.getLogger(__name__)


class SchedulerExecutionLogRepository:
    """调度器执行日志仓库（异步版本，用于 API 查询）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent_logs(
        self,
        limit: int = 50,
        event_type: SchedulerEventType | None = None,
        since: datetime | None = None,
    ) -> list[SchedulerExecutionLog]:
        """查询最近的执行日志。

        Args:
            limit: 返回记录数上限
            event_type: 可选的事件类型过滤
            since: 可选的起始时间过滤

        Returns:
            list[SchedulerExecutionLog]: 按 executed_at 降序排列的日志列表
        """
        stmt = select(SchedulerExecutionLogOrm).order_by(
            SchedulerExecutionLogOrm.executed_at.desc()
        )
        if event_type is not None:
            stmt = stmt.where(
                SchedulerExecutionLogOrm.event_type == event_type.value
            )
        if since is not None:
            stmt = stmt.where(SchedulerExecutionLogOrm.executed_at >= since)
        stmt = stmt.limit(limit)

        result = await self._session.execute(stmt)
        return [row.to_domain() for row in result.scalars().all()]

    async def cleanup_old_logs(self, retention_days: int = 30) -> int:
        """清理过期的执行日志。

        Args:
            retention_days: 保留天数

        Returns:
            int: 删除的记录数
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = delete(SchedulerExecutionLogOrm).where(
            SchedulerExecutionLogOrm.executed_at < cutoff
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount


class SchedulerExecutionLogSyncWriter:
    """调度器执行日志同步写入器。

    供 APScheduler 回调线程使用，通过同步引擎写入数据库。
    写入失败仅记录错误日志，不会影响调度器运行。
    """

    @staticmethod
    def write_log(log: SchedulerExecutionLog) -> None:
        """同步写入一条执行日志。

        Args:
            log: 待写入的日志领域模型
        """
        try:
            from sqlalchemy.orm import Session as SyncSession

            from src.database.models import get_engine

            engine = get_engine()
            with SyncSession(engine) as session:
                orm = SchedulerExecutionLogOrm.from_domain(log)
                session.add(orm)
                session.commit()
        except Exception as e:
            logger.error(f"写入调度器执行日志失败: {e}", exc_info=True)
