"""主题管理业务服务。"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_layer.provider import get_topic_store
from src.database.models import ScraperFollow
from src.topic.domain.models import TopicAccountDomain, TopicDetailDomain, TopicDomain, TopicWithCountDomain

logger = logging.getLogger(__name__)


class TopicService:
    """主题 CRUD 和账号管理业务服务。"""

    async def create_topic(
        self, session: AsyncSession, name: str, description: str | None = None, user_id: int | None = None
    ) -> TopicDomain:
        """创建主题。同一用户下名称重复时抛出 ValueError。"""
        store = get_topic_store(session)
        if await store.get_by_name(name, user_id=user_id):
            raise ValueError(f"主题名称 '{name}' 已存在")
        created = await store.create(name=name, description=description, user_id=user_id)
        await session.commit()
        return created

    async def list_topics(self, session: AsyncSession, user_id: int | None = None) -> list[TopicWithCountDomain]:
        """列出主题（按创建时间倒序），包含关联账号数量。

        Args:
            user_id: 非 None 时只返回该用户的主题，None 时返回全部。
        """
        return await get_topic_store(session).list_all(user_id=user_id)

    async def get_topic(self, session: AsyncSession, topic_id: int) -> TopicDetailDomain | None:
        """获取主题详情（含账号列表）。不存在返回 None。"""
        return await get_topic_store(session).get_by_id(topic_id)

    async def update_topic(
        self, session: AsyncSession, topic_id: int,
        name: str | None = None, description: str | None = None
    ) -> TopicDomain | None:
        """更新主题。不存在返回 None，名称重复抛出 ValueError。"""
        store = get_topic_store(session)
        topic = await store.get_by_id(topic_id)        # TopicDetailDomain
        if not topic:
            return None
        if name is not None and name != topic.name:
            if await store.get_by_name(name, user_id=topic.user_id):
                raise ValueError(f"主题名称 '{name}' 已存在")
            topic.name = name
        if description is not None:
            topic.description = description
        result = await store.update(topic)             # adapter 读 .id/.name/.description/.user_id
        await session.commit()
        return result

    async def delete_topic(self, session: AsyncSession, topic_id: int) -> bool:
        """删除主题（级联删除）。不存在返回 False。"""
        result = await get_topic_store(session).delete(topic_id)
        if result:
            await session.commit()
        return result

    # ── 账号管理 ──

    async def add_account(
        self, session: AsyncSession, topic_id: int, username: str
    ) -> TopicAccountDomain:
        """添加账号到主题。验证 scraper_follows 存在性和账号唯一性。"""
        store = get_topic_store(session)
        if not await store.get_by_id(topic_id):
            raise ValueError(f"主题 ID {topic_id} 不存在")
        await self._validate_username_in_scraper_follows(session, username)
        if await store.get_account(topic_id, username):
            raise ValueError(f"账号 '{username}' 已关联到该主题")
        created = await store.add_account(topic_id, username)
        await session.commit()
        return created

    async def remove_account(
        self, session: AsyncSession, topic_id: int, username: str
    ) -> bool:
        """从主题移除账号。不存在返回 False。"""
        result = await get_topic_store(session).delete_account(topic_id, username)
        if result:
            await session.commit()
        return result

    async def set_accounts(
        self, session: AsyncSession, topic_id: int, usernames: list[str]
    ) -> list[TopicAccountDomain]:
        """批量设置主题账号（替换模式）。验证所有用户名存在于 scraper_follows。"""
        store = get_topic_store(session)
        if not await store.get_by_id(topic_id):
            raise ValueError(f"主题 ID {topic_id} 不存在")
        for username in usernames:
            await self._validate_username_in_scraper_follows(session, username)
        result = await store.replace_accounts(topic_id, usernames)
        await session.commit()
        return result

    async def _validate_username_in_scraper_follows(
        self, session: AsyncSession, username: str
    ) -> None:
        """验证用户名存在于 scraper_follows 表。不存在时抛出 ValueError。"""
        stmt = select(ScraperFollow).where(ScraperFollow.username == username)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ValueError(f"账号 '{username}' 未在系统抓取列表中注册")
