"""用户生命周期编排服务。"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from src.user.domain.models import UserDomain, ApiKeyInfo
from src.user.infrastructure.repository import UserRepository, NotFoundError
from src.user.services.auth_service import AuthService

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = UserRepository(session)
        self._auth = AuthService()

    async def create_user(self, name: str, email: str) -> tuple[UserDomain, str, str]:
        """创建用户。返回 (user, temp_password, raw_api_key)。"""
        # 生成临时密码
        temp_password = self._auth.generate_temp_password()
        password_hash = await self._auth.hash_password(temp_password)

        # 创建用户
        user = await self._repo.create_user(name, email, password_hash)

        # 生成默认 API Key
        raw_key, key_hash, key_prefix = self._auth.generate_api_key()
        await self._repo.create_api_key(user.id, key_hash, key_prefix, "default")

        # 初始化关注列表（可选，需要 PreferenceService）
        try:
            from src.preference.infrastructure.preference_repository import PreferenceRepository
            from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository
            from src.preference.services.preference_service import PreferenceService

            pref_repo = PreferenceRepository(self._session)
            scraper_repo = ScraperConfigRepository(self._session)
            pref_service = PreferenceService(pref_repo, scraper_repo)
            await pref_service.initialize_user_follows(user.id)
        except Exception as e:
            logger.warning(f"初始化关注列表失败（非致命）: {e}")

        return user, temp_password, raw_key

    async def create_api_key(self, user_id: int, name: str = "default") -> tuple[ApiKeyInfo, str]:
        """创建 API Key。返回 (key_info, raw_key)。"""
        raw_key, key_hash, key_prefix = self._auth.generate_api_key()
        key_info = await self._repo.create_api_key(user_id, key_hash, key_prefix, name)
        return key_info, raw_key

    async def revoke_api_key(self, user_id: int, key_id: int) -> None:
        """撤销 API Key。验证 key 属于 user_id。"""
        keys = await self._repo.get_keys_by_user(user_id)
        if not any(k.id == key_id for k in keys):
            raise NotFoundError("API Key 不存在")
        await self._repo.deactivate_key(key_id)

    async def list_api_keys(self, user_id: int) -> list[ApiKeyInfo]:
        return await self._repo.get_keys_by_user(user_id)

    async def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        """修改密码。旧密码错误抛出 ValueError。"""
        user_orm = await self._repo.get_user_orm_by_id(user_id)
        if user_orm is None:
            raise NotFoundError("用户不存在")

        if not await self._auth.verify_password(old_password, user_orm.password_hash):
            raise ValueError("旧密码不正确")

        new_hash = await self._auth.hash_password(new_password)
        await self._repo.update_password_hash(user_id, new_hash)

    async def reset_password(self, user_id: int) -> str:
        """管理员重置密码。返回新临时密码。"""
        user = await self._repo.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        temp_password = self._auth.generate_temp_password()
        password_hash = await self._auth.hash_password(temp_password)
        await self._repo.update_password_hash(user_id, password_hash)
        return temp_password

    async def get_user(self, user_id: int) -> UserDomain | None:
        return await self._repo.get_user_by_id(user_id)

    async def list_users(self) -> list[UserDomain]:
        return await self._repo.get_all_users()
