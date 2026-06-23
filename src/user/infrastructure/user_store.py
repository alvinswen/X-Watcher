# src/user/infrastructure/user_store.py
"""UserStore 契约(14 方法)+ 契约异常。两实现共享:oracle(vendored 旧 repo)与文件 candidate。

参数式接口(收散列参数、返回 domain,异于 clustering 的 domain-passing):
- create_user/create_api_key/update_user 收散列参数,实现分配自增 id(两表各自 seq)。
- get_password_hash_by_id/email:ORM-leaky get_user_orm_* 的重表达(owner brainstorm 定 (b)),
  返回 password_hash 字符串或 None(用户不存在/无哈希均 None);oracle wrapper 调 vendored
  get_user_orm_*().password_hash 桥接。
- update_password_hash/update_key_last_used 缺 id 静默 no-op(复刻旧 bulk update 无 NotFound)。
- deactivate_key 软态(翻 is_active,行不删);缺 id → NotFoundError(唯一会抛 NotFound 的写)。
异常面:email 唯一性进 parity(两侧 DuplicateError);key_hash 唯一性入 invariant(旧抛裸 IntegrityError、
candidate 抛 DuplicateError,类型不一致出 parity);NotFoundError 进 parity(update_user/deactivate_key 两侧)。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.user.domain.models import ApiKeyInfo, UserDomain


class RepositoryError(Exception):
    """仓库操作错误。"""


class NotFoundError(RepositoryError):
    """记录未找到错误(update_user/deactivate_key 缺 id,进 parity)。"""


class DuplicateError(RepositoryError):
    """重复记录错误(email 唯一性进 parity;key_hash 唯一性 candidate 强制,入 invariant)。"""


@runtime_checkable
class UserStore(Protocol):
    # —— users ——
    async def create_user(self, name: str, email: str, password_hash: str) -> UserDomain: ...
    async def get_user_by_id(self, user_id: int) -> UserDomain | None: ...
    async def get_user_by_email(self, email: str) -> UserDomain | None: ...
    async def get_password_hash_by_id(self, user_id: int) -> str | None: ...
    async def get_password_hash_by_email(self, email: str) -> str | None: ...
    async def get_all_users(self) -> list[UserDomain]: ...
    async def update_user(self, user_id: int, name: str | None = None,
                          email: str | None = None, is_admin: bool | None = None) -> UserDomain: ...
    async def count_admins(self) -> int: ...
    async def update_password_hash(self, user_id: int, password_hash: str) -> None: ...
    # —— api_keys ——
    async def create_api_key(self, user_id: int, key_hash: str, key_prefix: str,
                             name: str = "default") -> ApiKeyInfo: ...
    async def get_active_key_by_hash(self, key_hash: str) -> tuple[ApiKeyInfo, int] | None: ...
    async def get_keys_by_user(self, user_id: int) -> list[ApiKeyInfo]: ...
    async def deactivate_key(self, key_id: int) -> None: ...
    async def update_key_last_used(self, key_id: int) -> None: ...
