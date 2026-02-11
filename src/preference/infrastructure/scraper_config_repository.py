"""ScraperConfigRepository - 平台抓取配置数据访问层。

管理员维护的平台级 Twitter 关注列表的数据库 CRUD 操作。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperFollow as ScraperFollowOrm
from src.preference.domain.models import ScraperFollow as ScraperFollowDomain

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


class ScraperConfigRepository:
    """平台抓取配置仓库。

    负责管理员维护的平台级抓取账号列表的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化仓库。

        Args:
            session: 异步数据库会话
        """
        self._session = session

    async def create_scraper_follow(
        self,
        username: str,
        reason: str,
        added_by: str,
    ) -> ScraperFollowDomain:
        """创建抓取账号记录。

        Args:
            username: Twitter 用户名
            reason: 添加理由
            added_by: 添加人标识

        Returns:
            ScraperFollowDomain: 创建的抓取账号记录

        Raises:
            DuplicateError: 如果用户名已存在
            RepositoryError: 如果创建失败
        """
        try:
            orm_follow = ScraperFollowOrm(
                username=username,
                added_at=datetime.now(timezone.utc),
                reason=reason,
                added_by=added_by,
                is_active=True,
            )
            self._session.add(orm_follow)
            await self._session.flush()

            logger.debug(f"创建抓取账号: username={username}, added_by={added_by}")
            return ScraperFollowDomain.from_orm(orm_follow)

        except IntegrityError as e:
            await self._session.rollback()
            logger.debug(f"抓取账号已存在: username={username}")
            raise DuplicateError(
                f"抓取账号已存在: {username}"
            ) from e

        except Exception as e:
            await self._session.rollback()
            logger.error(f"创建抓取账号失败: {e}")
            raise RepositoryError(f"创建抓取账号失败: {e}") from e

    async def get_all_follows(
        self,
        include_inactive: bool = False,
    ) -> list[ScraperFollowDomain]:
        """获取所有抓取账号。

        Args:
            include_inactive: 是否包含禁用的账号

        Returns:
            list[ScraperFollowDomain]: 抓取账号列表
        """
        try:
            stmt = select(ScraperFollowOrm).order_by(ScraperFollowOrm.added_at.desc())

            if not include_inactive:
                stmt = stmt.where(ScraperFollowOrm.is_active == True)

            result = await self._session.execute(stmt)
            orm_follows = result.scalars().all()

            return [ScraperFollowDomain.from_orm(f) for f in orm_follows]

        except Exception as e:
            logger.error(f"获取抓取账号列表失败: {e}")
            raise RepositoryError(f"获取抓取账号列表失败: {e}") from e

    async def get_active_follows(self) -> list[ScraperFollowDomain]:
        """获取所有启用的抓取账号。

        Returns:
            list[ScraperFollowDomain]: 启用的抓取账号列表
        """
        return await self.get_all_follows(include_inactive=False)

    async def get_follow_by_username(
        self,
        username: str,
    ) -> ScraperFollowDomain | None:
        """根据用户名查询抓取账号。

        Args:
            username: Twitter 用户名

        Returns:
            ScraperFollowDomain 或 None
        """
        try:
            stmt = select(ScraperFollowOrm).where(
                ScraperFollowOrm.username == username,
            )
            result = await self._session.execute(stmt)
            orm_follow = result.scalar_one_or_none()

            if orm_follow is None:
                return None

            return ScraperFollowDomain.from_orm(orm_follow)

        except Exception as e:
            logger.error(f"查询抓取账号失败: {e}")
            raise RepositoryError(f"查询抓取账号失败: {e}") from e

    async def update_scraper_follow(
        self,
        username: str,
        reason: str | None = None,
        is_active: bool | None = None,
    ) -> ScraperFollowDomain:
        """更新抓取账号。

        Args:
            username: Twitter 用户名
            reason: 新的添加理由（可选）
            is_active: 是否启用（可选）

        Returns:
            ScraperFollowDomain: 更新后的抓取账号记录

        Raises:
            NotFoundError: 如果账号不存在
            RepositoryError: 如果没有提供任何更新参数或更新失败
        """
        try:
            # 验证至少有一个更新参数
            if reason is None and is_active is None:
                raise RepositoryError("必须提供至少一个更新参数（reason 或 is_active）")

            # 查询记录
            stmt = select(ScraperFollowOrm).where(
                ScraperFollowOrm.username == username,
            )
            result = await self._session.execute(stmt)
            orm_follow = result.scalar_one_or_none()

            if orm_follow is None:
                raise NotFoundError(f"抓取账号不存在: {username}")

            # 更新字段
            if reason is not None:
                orm_follow.reason = reason
            if is_active is not None:
                orm_follow.is_active = is_active

            await self._session.flush()

            logger.debug(f"更新抓取账号: username={username}")
            return ScraperFollowDomain.from_orm(orm_follow)

        except NotFoundError:
            raise

        except Exception as e:
            await self._session.rollback()
            logger.error(f"更新抓取账号失败: {e}")
            raise RepositoryError(f"更新抓取账号失败: {e}") from e

    async def deactivate_follow(
        self,
        username: str,
    ) -> None:
        """禁用抓取账号（软删除）。

        Args:
            username: Twitter 用户名

        Raises:
            NotFoundError: 如果账号不存在
            RepositoryError: 如果禁用失败
        """
        try:
            # 查询记录
            stmt = select(ScraperFollowOrm).where(
                ScraperFollowOrm.username == username,
            )
            result = await self._session.execute(stmt)
            orm_follow = result.scalar_one_or_none()

            if orm_follow is None:
                raise NotFoundError(f"抓取账号不存在: {username}")

            # 软删除
            orm_follow.is_active = False
            await self._session.flush()

            logger.debug(f"禁用抓取账号: username={username}")

        except NotFoundError:
            raise

        except Exception as e:
            await self._session.rollback()
            logger.error(f"禁用抓取账号失败: {e}")
            raise RepositoryError(f"禁用抓取账号失败: {e}") from e

    async def is_username_in_follows(
        self,
        username: str,
        active_only: bool = True,
    ) -> bool:
        """检查用户名是否在抓取列表中。

        Args:
            username: Twitter 用户名
            active_only: 是否只检查启用的账号

        Returns:
            bool: 如果用户名存在返回 True，否则返回 False
        """
        try:
            stmt = select(ScraperFollowOrm.id).where(
                ScraperFollowOrm.username == username,
            )

            if active_only:
                stmt = stmt.where(ScraperFollowOrm.is_active == True)

            result = await self._session.execute(stmt)
            return result.scalar_one_or_none() is not None

        except Exception as e:
            logger.error(f"检查用户名是否在抓取列表中失败: {e}")
            raise RepositoryError(f"检查用户名是否在抓取列表中失败: {e}") from e
