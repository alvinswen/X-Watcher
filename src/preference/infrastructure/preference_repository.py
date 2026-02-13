"""PreferenceRepository - 用户关注列表数据访问层。

管理用户关注列表的数据库 CRUD 操作。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import TwitterFollow
from src.preference.domain.models import (
    TwitterFollow as TwitterFollowDomain,
)

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """仓库操作错误。"""

    pass


class NotFoundError(RepositoryError):
    """资源未找到错误。"""

    pass


class DuplicateError(RepositoryError):
    """重复记录错误。"""

    pass


class PreferenceRepository:
    """用户关注列表仓库。

    负责用户关注列表的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化仓库。

        Args:
            session: 异步数据库会话
        """
        self._session = session

    # ==================== TwitterFollow CRUD ====================

    async def create_follow(
        self,
        user_id: int,
        username: str,
    ) -> "TwitterFollowDomain":
        """创建关注记录。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名

        Returns:
            TwitterFollowDomain: 创建的关注记录

        Raises:
            DuplicateError: 如果关注已存在
            RepositoryError: 如果创建失败
        """
        try:
            orm_follow = TwitterFollow(
                user_id=user_id,
                username=username,
                created_at=datetime.now(timezone.utc),
            )
            self._session.add(orm_follow)
            await self._session.flush()

            logger.debug(f"创建关注记录: user_id={user_id}, username={username}")
            return TwitterFollowDomain.from_orm(orm_follow)

        except IntegrityError as e:
            await self._session.rollback()
            logger.debug(f"关注记录已存在: user_id={user_id}, username={username}")
            raise DuplicateError(
                f"关注记录已存在: {username}"
            ) from e

        except Exception as e:
            await self._session.rollback()
            logger.error(f"创建关注记录失败: {e}")
            raise RepositoryError(f"创建关注记录失败: {e}") from e

    async def get_follow_by_username(
        self,
        user_id: int,
        username: str,
    ) -> "TwitterFollowDomain | None":
        """根据用户名查询关注记录。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名

        Returns:
            TwitterFollowDomain 或 None
        """
        try:
            stmt = select(TwitterFollow).where(
                TwitterFollow.user_id == user_id,
                TwitterFollow.username == username,
            )
            result = await self._session.execute(stmt)
            orm_follow = result.scalar_one_or_none()

            if orm_follow is None:
                return None

            return TwitterFollowDomain.from_orm(orm_follow)

        except Exception as e:
            logger.error(f"查询关注记录失败: {e}")
            raise RepositoryError(f"查询关注记录失败: {e}") from e

    async def get_follows_by_user(
        self,
        user_id: int,
    ) -> list["TwitterFollowDomain"]:
        """查询用户的所有关注记录。

        Args:
            user_id: 用户 ID

        Returns:
            list[TwitterFollowDomain]: 关注记录列表（按创建时间倒序）
        """
        try:
            stmt = select(TwitterFollow).where(
                TwitterFollow.user_id == user_id,
            ).order_by(TwitterFollow.created_at.desc())

            result = await self._session.execute(stmt)
            orm_follows = result.scalars().all()

            return [
                TwitterFollowDomain.from_orm(f) for f in orm_follows
            ]

        except Exception as e:
            logger.error(f"查询用户关注列表失败: {e}")
            raise RepositoryError(f"查询用户关注列表失败: {e}") from e

    async def delete_follow(
        self,
        user_id: int,
        username: str,
    ) -> None:
        """删除关注记录。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名

        Note:
            如果关注记录不存在，不抛出错误（幂等操作）
        """
        try:
            stmt = delete(TwitterFollow).where(
                TwitterFollow.user_id == user_id,
                TwitterFollow.username == username,
            )
            await self._session.execute(stmt)
            await self._session.flush()

            logger.debug(f"删除关注记录: user_id={user_id}, username={username}")

        except Exception as e:
            logger.error(f"删除关注记录失败: {e}")
            raise RepositoryError(f"删除关注记录失败: {e}") from e

    async def user_has_follows(self, user_id: int) -> bool:
        """检查用户是否有关注记录。

        Args:
            user_id: 用户 ID

        Returns:
            bool: 如果用户有关注记录返回 True，否则返回 False
        """
        try:
            from sqlalchemy import func

            stmt = select(func.count(TwitterFollow.id)).where(
                TwitterFollow.user_id == user_id,
            )
            result = await self._session.execute(stmt)
            count = result.scalar() or 0

            return count > 0

        except Exception as e:
            logger.error(f"检查用户关注状态失败: {e}")
            raise RepositoryError(f"检查用户关注状态失败: {e}") from e

    async def batch_create_follows(
        self,
        user_id: int,
        usernames: list[str],
    ) -> list["TwitterFollowDomain"]:
        """批量创建关注记录。

        Args:
            user_id: 用户 ID
            usernames: Twitter 用户名列表

        Returns:
            list[TwitterFollowDomain]: 创建的关注记录列表

        Raises:
            DuplicateError: 如果存在重复的关注记录
            RepositoryError: 如果批量创建失败
        """
        try:
            follows = []
            for username in usernames:
                orm_follow = TwitterFollow(
                    user_id=user_id,
                    username=username,
                    created_at=datetime.now(timezone.utc),
                )
                self._session.add(orm_follow)
                follows.append(orm_follow)

            await self._session.flush()

            logger.debug(f"批量创建关注记录: user_id={user_id}, count={len(usernames)}")
            return [TwitterFollowDomain.from_orm(f) for f in follows]

        except IntegrityError as e:
            await self._session.rollback()
            logger.debug(f"批量创建关注记录时发现重复: user_id={user_id}")
            raise DuplicateError("批量创建关注记录时发现重复记录") from e

        except Exception as e:
            await self._session.rollback()
            logger.error(f"批量创建关注记录失败: {e}")
            raise RepositoryError(f"批量创建关注记录失败: {e}") from e
