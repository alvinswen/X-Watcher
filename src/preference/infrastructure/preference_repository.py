"""PreferenceRepository - 用户偏好数据访问层。

管理用户偏好配置的数据库 CRUD 操作。
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import TwitterFollow, FilterRule, Preference
from src.preference.domain.models import (
    FilterType,
    TwitterFollow as TwitterFollowDomain,
    FilterRule as FilterRuleDomain,
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
    """用户偏好仓库。

    负责用户关注列表、过滤规则和偏好配置的持久化和查询操作。
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
        priority: int = 5,
    ) -> "TwitterFollowDomain":
        """创建关注记录。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名
            priority: 优先级（1-10，默认 5）

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
                priority=priority,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
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
            list[TwitterFollowDomain]: 关注记录列表
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

    async def update_follow_priority(
        self,
        user_id: int,
        username: str,
        priority: int,
    ) -> "TwitterFollowDomain":
        """更新关注优先级。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名
            priority: 新优先级

        Returns:
            TwitterFollowDomain: 更新后的关注记录

        Raises:
            NotFoundError: 如果关注记录不存在
            RepositoryError: 如果更新失败
        """
        try:
            # 查询记录
            follow = await self.get_follow_by_username(user_id, username)
            if follow is None:
                raise NotFoundError(f"关注记录不存在: {username}")

            # 更新 ORM 对象
            stmt = select(TwitterFollow).where(
                TwitterFollow.user_id == user_id,
                TwitterFollow.username == username,
            )
            result = await self._session.execute(stmt)
            orm_follow = result.scalar_one_or_none()

            if orm_follow is None:
                raise NotFoundError(f"关注记录不存在: {username}")

            orm_follow.priority = priority
            orm_follow.updated_at = datetime.now(timezone.utc)
            await self._session.flush()

            logger.debug(f"更新关注优先级: user_id={user_id}, username={username}, priority={priority}")
            return TwitterFollowDomain.from_orm(orm_follow)

        except NotFoundError:
            raise

        except Exception as e:
            await self._session.rollback()
            logger.error(f"更新关注优先级失败: {e}")
            raise RepositoryError(f"更新关注优先级失败: {e}") from e

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
        default_priority: int = 5,
    ) -> list["TwitterFollowDomain"]:
        """批量创建关注记录。

        Args:
            user_id: 用户 ID
            usernames: Twitter 用户名列表
            default_priority: 默认优先级

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
                    priority=default_priority,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
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

    # ==================== FilterRule CRUD ====================

    async def create_filter(
        self,
        user_id: int,
        filter_type: FilterType,
        value: str,
    ) -> "FilterRuleDomain":
        """创建过滤规则。

        Args:
            user_id: 用户 ID
            filter_type: 过滤类型
            value: 过滤值

        Returns:
            FilterRuleDomain: 创建的过滤规则

        Raises:
            RepositoryError: 如果创建失败
        """
        try:
            rule_id = str(uuid.uuid4())
            orm_filter = FilterRule(
                id=rule_id,
                user_id=user_id,
                filter_type=filter_type.value,
                value=value,
                created_at=datetime.now(timezone.utc),
            )
            self._session.add(orm_filter)
            await self._session.flush()

            logger.debug(f"创建过滤规则: user_id={user_id}, type={filter_type.value}, value={value}")
            return FilterRuleDomain.from_orm(orm_filter)

        except Exception as e:
            await self._session.rollback()
            logger.error(f"创建过滤规则失败: {e}")
            raise RepositoryError(f"创建过滤规则失败: {e}") from e

    async def get_filters_by_user(
        self,
        user_id: int,
    ) -> list["FilterRuleDomain"]:
        """查询用户的所有过滤规则。

        Args:
            user_id: 用户 ID

        Returns:
            list[FilterRuleDomain]: 过滤规则列表
        """
        try:
            stmt = select(FilterRule).where(
                FilterRule.user_id == user_id,
            ).order_by(FilterRule.created_at.desc())

            result = await self._session.execute(stmt)
            orm_filters = result.scalars().all()

            return [FilterRuleDomain.from_orm(f) for f in orm_filters]

        except Exception as e:
            logger.error(f"查询用户过滤规则失败: {e}")
            raise RepositoryError(f"查询用户过滤规则失败: {e}") from e

    async def get_filter_by_id(
        self,
        rule_id: str,
    ) -> "FilterRuleDomain | None":
        """根据 ID 查询过滤规则。

        Args:
            rule_id: 规则 ID（UUID）

        Returns:
            FilterRuleDomain 或 None
        """
        try:
            stmt = select(FilterRule).where(FilterRule.id == rule_id)
            result = await self._session.execute(stmt)
            orm_filter = result.scalar_one_or_none()

            if orm_filter is None:
                return None

            return FilterRuleDomain.from_orm(orm_filter)

        except Exception as e:
            logger.error(f"查询过滤规则失败: {e}")
            raise RepositoryError(f"查询过滤规则失败: {e}") from e

    async def delete_filter(
        self,
        rule_id: str,
    ) -> None:
        """删除过滤规则。

        Args:
            rule_id: 规则 ID（UUID）

        Note:
            如果过滤规则不存在，不抛出错误（幂等操作）
        """
        try:
            stmt = delete(FilterRule).where(FilterRule.id == rule_id)
            await self._session.execute(stmt)
            await self._session.flush()

            logger.debug(f"删除过滤规则: rule_id={rule_id}")

        except Exception as e:
            logger.error(f"删除过滤规则失败: {e}")
            raise RepositoryError(f"删除过滤规则失败: {e}") from e

    # ==================== Preference CRUD ====================

    async def set_preference(
        self,
        user_id: int,
        key: str,
        value: str,
    ) -> None:
        """设置偏好配置。

        如果偏好已存在则更新，否则创建新记录。

        Args:
            user_id: 用户 ID
            key: 配置键
            value: 配置值

        Raises:
            RepositoryError: 如果设置失败
        """
        try:
            # 查询是否已存在
            stmt = select(Preference).where(
                Preference.user_id == user_id,
                Preference.key == key,
            )
            result = await self._session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # 更新现有记录
                existing.value = value
            else:
                # 创建新记录
                orm_pref = Preference(
                    user_id=user_id,
                    key=key,
                    value=value,
                )
                self._session.add(orm_pref)

            await self._session.flush()
            logger.debug(f"设置偏好配置: user_id={user_id}, key={key}, value={value}")

        except Exception as e:
            await self._session.rollback()
            logger.error(f"设置偏好配置失败: {e}")
            raise RepositoryError(f"设置偏好配置失败: {e}") from e

    async def get_preference(
        self,
        user_id: int,
        key: str,
    ) -> str | None:
        """获取偏好配置。

        Args:
            user_id: 用户 ID
            key: 配置键

        Returns:
            str | None: 配置值，如果不存在返回 None
        """
        try:
            stmt = select(Preference).where(
                Preference.user_id == user_id,
                Preference.key == key,
            )
            result = await self._session.execute(stmt)
            pref = result.scalar_one_or_none()

            if pref is None:
                return None

            return pref.value

        except Exception as e:
            logger.error(f"获取偏好配置失败: {e}")
            raise RepositoryError(f"获取偏好配置失败: {e}") from e

    async def get_all_preferences(
        self,
        user_id: int,
    ) -> dict[str, str]:
        """获取用户的所有偏好配置。

        Args:
            user_id: 用户 ID

        Returns:
            dict[str, str]: 配置键值对
        """
        try:
            stmt = select(Preference).where(
                Preference.user_id == user_id,
            )
            result = await self._session.execute(stmt)
            prefs = result.scalars().all()

            return {pref.key: pref.value for pref in prefs}

        except Exception as e:
            logger.error(f"获取所有偏好配置失败: {e}")
            raise RepositoryError(f"获取所有偏好配置失败: {e}") from e

    async def delete_preference(
        self,
        user_id: int,
        key: str,
    ) -> None:
        """删除偏好配置。

        Args:
            user_id: 用户 ID
            key: 配置键

        Note:
            如果偏好配置不存在，不抛出错误（幂等操作）
        """
        try:
            stmt = delete(Preference).where(
                Preference.user_id == user_id,
                Preference.key == key,
            )
            await self._session.execute(stmt)
            await self._session.flush()

            logger.debug(f"删除偏好配置: user_id={user_id}, key={key}")

        except Exception as e:
            logger.error(f"删除偏好配置失败: {e}")
            raise RepositoryError(f"删除偏好配置失败: {e}") from e
