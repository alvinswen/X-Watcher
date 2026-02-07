"""去重结果仓库。

管理去重组的 CRUD 操作。
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.deduplication.domain.models import DeduplicationGroup, DeduplicationType
from src.scraper.infrastructure.models import DeduplicationGroupOrm, TweetOrm

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """仓库操作错误。"""

    pass


class NotFoundError(RepositoryError):
    """资源未找到错误。"""

    pass


class DeduplicationRepository:
    """去重结果仓库。

    管理去重组的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化仓库。

        Args:
            session: 异步数据库会话
        """
        self._session = session

    async def save_groups(
        self, groups: list[DeduplicationGroup]
    ) -> list[DeduplicationGroup]:
        """保存去重组。

        Args:
            groups: 去重组列表

        Returns:
            保存后的去重组列表

        Raises:
            RepositoryError: 保存失败时抛出
        """
        try:
            result = []
            for group in groups:
                # 检查是否已存在
                existing = await self.get_group(group.group_id)
                if existing:
                    # 更新现有记录
                    await self._update_group(group)
                    result.append(group)
                else:
                    # 创建新记录
                    orm_group = DeduplicationGroupOrm.from_domain(group)
                    self._session.add(orm_group)
                    result.append(group)

            # 更新推文的 deduplication_group_id
            for group in groups:
                await self._update_tweet_deduplication(group)

            await self._session.flush()
            return result

        except Exception as e:
            logger.error(f"保存去重组失败: {e}")
            raise RepositoryError(f"保存去重组失败: {e}") from e

    async def _update_group(self, group: DeduplicationGroup) -> None:
        """更新现有去重组。

        Args:
            group: 去重组
        """
        stmt = (
            update(DeduplicationGroupOrm)
            .where(DeduplicationGroupOrm.group_id == group.group_id)
            .values(
                representative_tweet_id=group.representative_tweet_id,
                deduplication_type=group.deduplication_type.value,
                similarity_score=group.similarity_score,
                tweet_ids=group.tweet_ids,
            )
        )
        await self._session.execute(stmt)

    async def _update_tweet_deduplication(
        self, group: DeduplicationGroup
    ) -> None:
        """更新推文的去重组关联。

        Args:
            group: 去重组
        """
        # 更新组内所有推文的 deduplication_group_id
        stmt = (
            update(TweetOrm)
            .where(TweetOrm.tweet_id.in_(group.tweet_ids))
            .values(deduplication_group_id=group.group_id)
        )
        await self._session.execute(stmt)

    async def get_group(self, group_id: str) -> DeduplicationGroup | None:
        """查询去重组。

        Args:
            group_id: 去重组 ID

        Returns:
            DeduplicationGroup 或 None
        """
        stmt = select(DeduplicationGroupOrm).where(
            DeduplicationGroupOrm.group_id == group_id
        )
        result = await self._session.execute(stmt)
        orm_group = result.scalar_one_or_none()

        if orm_group is None:
            return None

        return orm_group.to_domain()

    async def find_by_tweet(self, tweet_id: str) -> DeduplicationGroup | None:
        """根据推文 ID 查询去重组。

        Args:
            tweet_id: 推文 ID

        Returns:
            DeduplicationGroup 或 None
        """
        stmt = select(DeduplicationGroupOrm).where(
            TweetOrm.tweet_id == tweet_id,
            TweetOrm.deduplication_group_id == DeduplicationGroupOrm.group_id,
        )
        result = await self._session.execute(stmt)
        orm_group = result.scalar_one_or_none()

        if orm_group is None:
            return None

        return orm_group.to_domain()

    async def delete_group(self, group_id: str) -> None:
        """删除去重组（撤销去重）。

        Args:
            group_id: 去重组 ID

        Raises:
            NotFoundError: 去重组不存在
        """
        # 先检查是否存在
        group = await self.get_group(group_id)
        if group is None:
            raise NotFoundError(f"去重组不存在: {group_id}")

        # 清除推文的去重组关联
        stmt = (
            update(TweetOrm)
            .where(TweetOrm.deduplication_group_id == group_id)
            .values(deduplication_group_id=None)
        )
        await self._session.execute(stmt)

        # 删除去重组记录
        stmt = select(DeduplicationGroupOrm).where(
            DeduplicationGroupOrm.group_id == group_id
        )
        result = await self._session.execute(stmt)
        orm_group = result.scalar_one_or_none()

        if orm_group:
            await self._session.delete(orm_group)

    async def get_groups_by_type(
        self, deduplication_type: DeduplicationType
    ) -> list[DeduplicationGroup]:
        """按类型查询去重组。

        Args:
            deduplication_type: 去重类型

        Returns:
            去重组列表
        """
        stmt = (
            select(DeduplicationGroupOrm)
            .where(
                DeduplicationGroupOrm.deduplication_type == deduplication_type.value
            )
            .order_by(DeduplicationGroupOrm.created_at.desc())
        )
        result = await self._session.execute(stmt)
        orm_groups = result.scalars().all()

        return [g.to_domain() for g in orm_groups]

    async def get_recent_groups(
        self, limit: int = 100
    ) -> list[DeduplicationGroup]:
        """查询最近创建的去重组。

        Args:
            limit: 最大返回数量

        Returns:
            去重组列表
        """
        stmt = (
            select(DeduplicationGroupOrm)
            .order_by(DeduplicationGroupOrm.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        orm_groups = result.scalars().all()

        return [g.to_domain() for g in orm_groups]

    @staticmethod
    def generate_group_id() -> str:
        """生成新的去重组 ID。

        Returns:
            UUID 字符串
        """
        return str(uuid.uuid4())
