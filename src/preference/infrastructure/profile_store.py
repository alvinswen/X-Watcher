"""ProfileStore 契约(6 方法)+ 异常。两实现共享:oracle(vendored 旧 repo)与文件 candidate。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.preference.domain.models import XUserProfile


class RepositoryError(Exception):
    """仓库操作错误。"""


@runtime_checkable
class ProfileStore(Protocol):
    async def upsert_profiles(self, profiles: list[XUserProfile],
                              raw_data_map: dict[str, dict[str, Any]] | None = None) -> int: ...
    async def get_profile_by_user_id(self, platform_user_id: str) -> XUserProfile | None: ...
    async def get_profiles_by_user_ids(self, user_ids: list[str]) -> list[XUserProfile]: ...
    async def get_all_profiles(self) -> list[XUserProfile]: ...
    async def get_profiles_by_usernames(self, usernames: list[str]) -> list[XUserProfile]: ...
    async def get_profile_by_username(self, username: str) -> XUserProfile | None: ...
