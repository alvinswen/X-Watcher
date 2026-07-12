"""用户生命周期编排服务。"""

import logging
from typing import Any

from src.user.domain.models import UserDomain, ApiKeyInfo
from src.user.infrastructure.user_store import NotFoundError
from src.data_layer.provider import get_user_repo
from src.user.services.auth_service import AuthService

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session: Any = None):
        self._session = session
        self._repo = get_user_repo(session)
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
        keys: list[ApiKeyInfo] = await self._repo.get_keys_by_user(user_id)
        return keys

    async def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        """修改密码。旧密码错误抛出 ValueError。"""
        password_hash = await self._repo.get_password_hash_by_id(user_id)
        if password_hash is None:
            raise NotFoundError("用户不存在")

        if not await self._auth.verify_password(old_password, password_hash):
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

    async def update_user(
        self,
        user_id: int,
        name: str | None = None,
        email: str | None = None,
        is_admin: bool | None = None,
    ) -> UserDomain:
        """管理员更新用户信息。不能将最后一个管理员降级。"""
        if is_admin is False:
            current_user = await self._repo.get_user_by_id(user_id)
            if current_user is None:
                from src.user.infrastructure.user_store import NotFoundError
                raise NotFoundError("用户不存在")
            if current_user.is_admin:
                admin_count = await self._repo.count_admins()
                if admin_count <= 1:
                    raise ValueError("不能将最后一个管理员降级为普通用户")

        updated: UserDomain = await self._repo.update_user(
            user_id, name=name, email=email, is_admin=is_admin
        )
        return updated

    async def get_user(self, user_id: int) -> UserDomain | None:
        user: UserDomain | None = await self._repo.get_user_by_id(user_id)
        return user

    async def list_users(self) -> list[UserDomain]:
        users: list[UserDomain] = await self._repo.get_all_users()
        return users
