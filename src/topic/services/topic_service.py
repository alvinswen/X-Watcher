"""主题管理业务服务。"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperFollow
from src.topic.domain.models import TopicAccountDomain, TopicDetailDomain, TopicDomain, TopicWithCountDomain
from src.topic.infrastructure.models import TopicAccountOrm, TopicOrm
from src.topic.infrastructure.repository import TopicRepository

logger = logging.getLogger(__name__)


class TopicService:
    """主题 CRUD 和账号管理业务服务。"""

    def __init__(self) -> None:
        self._repo = TopicRepository()

    async def create_topic(
        self, session: AsyncSession, name: str, description: str | None = None
    ) -> TopicDomain:
        """创建主题。名称重复时抛出 ValueError。"""
        existing = await self._repo.get_by_name(session, name)
        if existing:
            raise ValueError(f"主题名称 '{name}' 已存在")

        topic = TopicOrm.from_domain(name=name, description=description)
        created = await self._repo.create(session, topic)
        await session.commit()
        return created.to_domain()

    async def list_topics(self, session: AsyncSession) -> list[TopicWithCountDomain]:
        """列出所有主题（按创建时间倒序），包含关联账号数量。"""
        results = await self._repo.list_all(session)
        return [topic.to_domain_with_count(count) for topic, count in results]

    async def get_topic(self, session: AsyncSession, topic_id: int) -> TopicDetailDomain | None:
        """获取主题详情（含账号列表）。不存在返回 None。"""
        topic = await self._repo.get_by_id(session, topic_id)
        if not topic:
            return None
        return topic.to_detail_domain()

    async def update_topic(
        self, session: AsyncSession, topic_id: int,
        name: str | None = None, description: str | None = None
    ) -> TopicDomain | None:
        """更新主题。不存在返回 None，名称重复抛出 ValueError。"""
        topic = await self._repo.get_by_id(session, topic_id)
        if not topic:
            return None

        if name is not None and name != topic.name:
            existing = await self._repo.get_by_name(session, name)
            if existing:
                raise ValueError(f"主题名称 '{name}' 已存在")
            topic.name = name

        if description is not None:
            topic.description = description

        await self._repo.update(session, topic)
        await session.commit()
        return topic.to_domain()

    async def delete_topic(self, session: AsyncSession, topic_id: int) -> bool:
        """删除主题（级联删除）。不存在返回 False。"""
        result = await self._repo.delete(session, topic_id)
        if result:
            await session.commit()
        return result

    # ── 账号管理 ──

    async def add_account(
        self, session: AsyncSession, topic_id: int, username: str
    ) -> TopicAccountDomain:
        """添加账号到主题。验证 scraper_follows 存在性和账号唯一性。"""
        # 验证主题存在
        topic = await self._repo.get_by_id(session, topic_id)
        if not topic:
            raise ValueError(f"主题 ID {topic_id} 不存在")

        # 验证账号存在于 scraper_follows
        await self._validate_username_in_scraper_follows(session, username)

        # 检查账号是否已关联
        existing = await self._repo.get_account(session, topic_id, username)
        if existing:
            raise ValueError(f"账号 '{username}' 已关联到该主题")

        account = TopicAccountOrm(topic_id=topic_id, username=username)
        created = await self._repo.add_account(session, account)
        await session.commit()
        return created.to_domain()

    async def remove_account(
        self, session: AsyncSession, topic_id: int, username: str
    ) -> bool:
        """从主题移除账号。不存在返回 False。"""
        result = await self._repo.delete_account(session, topic_id, username)
        if result:
            await session.commit()
        return result

    async def set_accounts(
        self, session: AsyncSession, topic_id: int, usernames: list[str]
    ) -> list[TopicAccountDomain]:
        """批量设置主题账号（替换模式）。验证所有用户名存在于 scraper_follows。"""
        # 验证主题存在
        topic = await self._repo.get_by_id(session, topic_id)
        if not topic:
            raise ValueError(f"主题 ID {topic_id} 不存在")

        # 验证所有用户名
        for username in usernames:
            await self._validate_username_in_scraper_follows(session, username)

        accounts = [TopicAccountOrm(topic_id=topic_id, username=u) for u in usernames]
        result = await self._repo.replace_accounts(session, topic_id, accounts)
        await session.commit()
        return [a.to_domain() for a in result]

    async def _validate_username_in_scraper_follows(
        self, session: AsyncSession, username: str
    ) -> None:
        """验证用户名存在于 scraper_follows 表。不存在时抛出 ValueError。"""
        stmt = select(ScraperFollow).where(ScraperFollow.username == username)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ValueError(f"账号 '{username}' 未在系统抓取列表中注册")
