"""TopicStore 契约(11 方法)+ 异常。两实现共享:oracle(vendored 旧 repo)与文件 candidate。

参数式接口(同 follows create_scraper_follow,非传 ORM);返回域模型。
异常面:parity 零自定义异常(全返回值对比);DuplicateError 是文件层 changed(出 parity 入 invariant)。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.topic.domain.models import (
    TopicAccountDomain,
    TopicDetailDomain,
    TopicDomain,
    TopicWithCountDomain,
)


class RepositoryError(Exception):
    """仓库操作错误。"""


class NotFoundError(RepositoryError):
    """资源未找到(candidate update 防御用,parity 不测)。"""


class DuplicateError(RepositoryError):
    """唯一性冲突(文件层手动强制,changed,出 parity 入 invariant)。"""


@runtime_checkable
class TopicStore(Protocol):
    # —— 话题 ——
    async def create(self, name: str, description: str | None = None,
                     user_id: int | None = None) -> TopicDomain: ...
    async def get_by_id(self, topic_id: int) -> TopicDetailDomain | None: ...
    async def get_by_name(self, name: str, user_id: int | None = None) -> TopicDomain | None: ...
    async def list_all(self, user_id: int | None = None) -> list[TopicWithCountDomain]: ...
    async def update(self, topic: TopicDomain) -> TopicDomain: ...
    async def delete(self, topic_id: int) -> bool: ...
    # —— 账号 ——
    async def add_account(self, topic_id: int, username: str) -> TopicAccountDomain: ...
    async def get_account(self, topic_id: int, username: str) -> TopicAccountDomain | None: ...
    async def get_accounts(self, topic_id: int) -> list[TopicAccountDomain]: ...
    async def delete_account(self, topic_id: int, username: str) -> bool: ...
    async def replace_accounts(self, topic_id: int, usernames: list[str]) -> list[TopicAccountDomain]: ...
