"""ScraperScheduleRepository - 调度配置数据访问层。

管理调度配置的数据库 CRUD 操作（singleton 单行模式）。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperScheduleConfig as ScraperScheduleConfigOrm
from src.preference.domain.models import ScraperScheduleConfig as ScraperScheduleConfigDomain

logger = logging.getLogger(__name__)


class ScraperScheduleRepository:
    """调度配置仓库。

    管理 scraper_schedule_config 表的单行记录（id=1）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_schedule_config(self) -> ScraperScheduleConfigDomain | None:
        """获取调度配置。返回 None 表示无配置记录。"""
        stmt = select(ScraperScheduleConfigOrm).where(
            ScraperScheduleConfigOrm.id == 1
        )
        result = await self._session.execute(stmt)
        orm_obj = result.scalar_one_or_none()

        if orm_obj is None:
            return None

        return ScraperScheduleConfigDomain.from_orm(orm_obj)

    async def upsert_schedule_config(
        self,
        interval_seconds: int | None = None,
        next_run_time: datetime | None = None,
        is_enabled: bool | None = None,
        updated_by: str = "",
    ) -> ScraperScheduleConfigDomain:
        """创建或更新调度配置。至少需提供一个配置参数。"""
        stmt = select(ScraperScheduleConfigOrm).where(
            ScraperScheduleConfigOrm.id == 1
        )
        result = await self._session.execute(stmt)
        orm_obj = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if orm_obj is None:
            # 创建新记录
            orm_obj = ScraperScheduleConfigOrm(
                id=1,
                interval_seconds=interval_seconds if interval_seconds is not None else 43200,
                next_run_time=next_run_time,
                is_enabled=is_enabled if is_enabled is not None else True,
                updated_at=now,
                updated_by=updated_by,
            )
            self._session.add(orm_obj)
        else:
            # 更新已有记录
            if interval_seconds is not None:
                orm_obj.interval_seconds = interval_seconds
            if next_run_time is not None:
                orm_obj.next_run_time = next_run_time
            if is_enabled is not None:
                orm_obj.is_enabled = is_enabled
            orm_obj.updated_at = now
            orm_obj.updated_by = updated_by

        await self._session.flush()

        logger.debug(
            f"调度配置已更新: interval={orm_obj.interval_seconds}, "
            f"next_run={orm_obj.next_run_time}, enabled={orm_obj.is_enabled}, "
            f"by={updated_by}"
        )
        return ScraperScheduleConfigDomain.from_orm(orm_obj)
