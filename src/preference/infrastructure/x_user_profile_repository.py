"""XUserProfileRepository - X 平台用户档案数据访问层。

管理 x_user_profiles 表的 CRUD 操作。
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.x_user_profile_model import XUserProfileOrm
from src.preference.domain.models import XUserProfile
from src.preference.infrastructure.scraper_config_repository import RepositoryError

logger = logging.getLogger(__name__)


class XUserProfileRepository:
    """X 平台用户档案仓库。

    负责用户档案信息的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_profiles(
        self,
        profiles: list[XUserProfile],
        raw_data_map: dict[str, dict] | None = None,
    ) -> int:
        """批量插入或更新用户档案。

        使用 session.merge() 实现 upsert 语义（SQLite 兼容）。

        Args:
            profiles: 用户档案领域模型列表
            raw_data_map: 可选，{platform_user_id: 原始API响应dict}

        Returns:
            int: 处理的档案数量
        """
        try:
            count = 0
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            for profile in profiles:
                if not profile.platform_user_id:
                    continue

                raw_json = None
                if raw_data_map and profile.platform_user_id in raw_data_map:
                    raw_json = json.dumps(
                        raw_data_map[profile.platform_user_id],
                        ensure_ascii=False,
                    )

                orm_obj = XUserProfileOrm(
                    platform_user_id=profile.platform_user_id,
                    username=profile.username,
                    display_name=profile.display_name,
                    is_blue_verified=profile.is_blue_verified,
                    verified_type=profile.verified_type,
                    profile_picture=profile.profile_picture,
                    cover_picture=profile.cover_picture,
                    description=profile.description,
                    location=profile.location,
                    followers_count=profile.followers_count,
                    following_count=profile.following_count,
                    statuses_count=profile.statuses_count,
                    favourites_count=profile.favourites_count,
                    media_count=profile.media_count,
                    account_created_at=profile.account_created_at,
                    is_automated=profile.is_automated,
                    possibly_sensitive=profile.possibly_sensitive,
                    pinned_tweet_ids=profile.pinned_tweet_ids,
                    unavailable=profile.unavailable,
                    unavailable_reason=profile.unavailable_reason,
                    raw_json=raw_json,
                    fetched_at=profile.fetched_at or now,
                    updated_at=now,
                )

                # 检查是否已存在
                existing = await self._session.get(
                    XUserProfileOrm, profile.platform_user_id
                )
                if existing is None:
                    orm_obj.created_at = now
                    self._session.add(orm_obj)
                else:
                    # 更新已有记录
                    existing.username = orm_obj.username
                    existing.display_name = orm_obj.display_name
                    existing.is_blue_verified = orm_obj.is_blue_verified
                    existing.verified_type = orm_obj.verified_type
                    existing.profile_picture = orm_obj.profile_picture
                    existing.cover_picture = orm_obj.cover_picture
                    existing.description = orm_obj.description
                    existing.location = orm_obj.location
                    existing.followers_count = orm_obj.followers_count
                    existing.following_count = orm_obj.following_count
                    existing.statuses_count = orm_obj.statuses_count
                    existing.favourites_count = orm_obj.favourites_count
                    existing.media_count = orm_obj.media_count
                    existing.account_created_at = orm_obj.account_created_at
                    existing.is_automated = orm_obj.is_automated
                    existing.possibly_sensitive = orm_obj.possibly_sensitive
                    existing.pinned_tweet_ids = orm_obj.pinned_tweet_ids
                    existing.unavailable = orm_obj.unavailable
                    existing.unavailable_reason = orm_obj.unavailable_reason
                    existing.raw_json = orm_obj.raw_json
                    existing.fetched_at = orm_obj.fetched_at
                    existing.updated_at = now

                count += 1

            await self._session.flush()
            logger.debug("批量 upsert 用户档案: %d 条", count)
            return count

        except Exception as e:
            await self._session.rollback()
            logger.error("批量 upsert 用户档案失败: %s", e)
            raise RepositoryError(f"批量 upsert 用户档案失败: {e}") from e

    async def get_profile_by_user_id(
        self,
        platform_user_id: str,
    ) -> XUserProfile | None:
        """根据 platform_user_id 查询用户档案。"""
        try:
            orm_obj = await self._session.get(XUserProfileOrm, platform_user_id)
            if orm_obj is None:
                return None
            return XUserProfile.from_orm(orm_obj)
        except Exception as e:
            logger.error("查询用户档案失败: %s", e)
            raise RepositoryError(f"查询用户档案失败: {e}") from e

    async def get_profiles_by_user_ids(
        self,
        user_ids: list[str],
    ) -> list[XUserProfile]:
        """根据多个 platform_user_id 批量查询用户档案。"""
        try:
            if not user_ids:
                return []
            stmt = select(XUserProfileOrm).where(
                XUserProfileOrm.platform_user_id.in_(user_ids)
            )
            result = await self._session.execute(stmt)
            return [XUserProfile.from_orm(r) for r in result.scalars().all()]
        except Exception as e:
            logger.error("批量查询用户档案失败: %s", e)
            raise RepositoryError(f"批量查询用户档案失败: {e}") from e

    async def get_all_profiles(self) -> list[XUserProfile]:
        """获取所有用户档案。"""
        try:
            stmt = select(XUserProfileOrm).order_by(
                XUserProfileOrm.fetched_at.desc()
            )
            result = await self._session.execute(stmt)
            return [XUserProfile.from_orm(r) for r in result.scalars().all()]
        except Exception as e:
            logger.error("获取所有用户档案失败: %s", e)
            raise RepositoryError(f"获取所有用户档案失败: {e}") from e

    async def get_profiles_by_usernames(
        self,
        usernames: list[str],
    ) -> list[XUserProfile]:
        """根据用户名列表批量查询用户档案（大小写不敏感）。"""
        try:
            if not usernames:
                return []
            lower_names = [u.lower() for u in usernames]
            stmt = select(XUserProfileOrm).where(
                func.lower(XUserProfileOrm.username).in_(lower_names)
            )
            result = await self._session.execute(stmt)
            return [XUserProfile.from_orm(r) for r in result.scalars().all()]
        except Exception as e:
            logger.error("按用户名列表批量查询档案失败: %s", e)
            raise RepositoryError(f"按用户名列表批量查询档案失败: {e}") from e

    async def get_profile_by_username(
        self,
        username: str,
    ) -> XUserProfile | None:
        """根据用户名查询用户档案。"""
        try:
            stmt = select(XUserProfileOrm).where(
                XUserProfileOrm.username == username
            )
            result = await self._session.execute(stmt)
            orm_obj = result.scalar_one_or_none()
            if orm_obj is None:
                return None
            return XUserProfile.from_orm(orm_obj)
        except Exception as e:
            logger.error("按用户名查询档案失败: %s", e)
            raise RepositoryError(f"按用户名查询档案失败: {e}") from e
