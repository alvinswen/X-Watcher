"""用户数据访问层。"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User as UserOrm, ApiKey as ApiKeyOrm
from src.user.domain.models import UserDomain, ApiKeyInfo

logger = logging.getLogger(__name__)


class DuplicateError(Exception):
    """重复记录错误。"""
    pass


class NotFoundError(Exception):
    """记录未找到错误。"""
    pass


class UserRepository:
    """用户和 API Key 数据操作。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_user(self, name: str, email: str, password_hash: str) -> UserDomain:
        """创建用户。IntegrityError -> DuplicateError。"""
        user = UserOrm(name=name, email=email, password_hash=password_hash, is_admin=False)
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as e:
            await self._session.rollback()
            raise DuplicateError(f"该邮箱已被注册: {email}") from e
        return UserDomain.from_orm(user)

    async def get_user_by_id(self, user_id: int) -> UserDomain | None:
        result = await self._session.execute(select(UserOrm).where(UserOrm.id == user_id))
        user = result.scalar_one_or_none()
        return UserDomain.from_orm(user) if user else None

    async def get_user_by_email(self, email: str) -> UserDomain | None:
        result = await self._session.execute(select(UserOrm).where(UserOrm.email == email))
        user = result.scalar_one_or_none()
        return UserDomain.from_orm(user) if user else None

    async def get_user_orm_by_id(self, user_id: int) -> UserOrm | None:
        """获取 ORM 对象（用于密码验证等需要 password_hash 的场景）。"""
        result = await self._session.execute(select(UserOrm).where(UserOrm.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_orm_by_email(self, email: str) -> UserOrm | None:
        """获取 ORM 对象。"""
        result = await self._session.execute(select(UserOrm).where(UserOrm.email == email))
        return result.scalar_one_or_none()

    async def get_all_users(self) -> list[UserDomain]:
        result = await self._session.execute(select(UserOrm))
        users = result.scalars().all()
        return [UserDomain.from_orm(u) for u in users]

    async def update_password_hash(self, user_id: int, password_hash: str) -> None:
        await self._session.execute(
            update(UserOrm).where(UserOrm.id == user_id).values(password_hash=password_hash)
        )
        await self._session.flush()

    async def create_api_key(
        self, user_id: int, key_hash: str, key_prefix: str, name: str = "default"
    ) -> ApiKeyInfo:
        key = ApiKeyOrm(
            user_id=user_id, key_hash=key_hash, key_prefix=key_prefix, name=name
        )
        self._session.add(key)
        await self._session.flush()
        return ApiKeyInfo.from_orm(key)

    async def get_active_key_by_hash(self, key_hash: str) -> tuple[ApiKeyInfo, int] | None:
        """返回 (key_info, user_id) 或 None。仅查询 is_active=True。"""
        result = await self._session.execute(
            select(ApiKeyOrm).where(
                ApiKeyOrm.key_hash == key_hash,
                ApiKeyOrm.is_active == True,  # noqa: E712
            )
        )
        key = result.scalar_one_or_none()
        if key is None:
            return None
        return ApiKeyInfo.from_orm(key), key.user_id

    async def get_keys_by_user(self, user_id: int) -> list[ApiKeyInfo]:
        result = await self._session.execute(
            select(ApiKeyOrm).where(ApiKeyOrm.user_id == user_id)
        )
        keys = result.scalars().all()
        return [ApiKeyInfo.from_orm(k) for k in keys]

    async def deactivate_key(self, key_id: int) -> None:
        result = await self._session.execute(
            select(ApiKeyOrm).where(ApiKeyOrm.id == key_id)
        )
        key = result.scalar_one_or_none()
        if key is None:
            raise NotFoundError(f"API Key 不存在: {key_id}")
        key.is_active = False
        await self._session.flush()

    async def update_key_last_used(self, key_id: int) -> None:
        await self._session.execute(
            update(ApiKeyOrm)
            .where(ApiKeyOrm.id == key_id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self._session.flush()
