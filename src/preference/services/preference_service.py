"""PreferenceService - 用户关注列表管理服务。

协调用户关注列表的业务逻辑。
"""

import logging

from src.preference.domain.models import TwitterFollow
from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    NotFoundError,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
)

logger = logging.getLogger(__name__)


class PreferenceService:
    """用户关注列表管理服务。

    管理用户的关注列表。
    """

    def __init__(
        self,
        preference_repository: PreferenceRepository,
        scraper_config_repository: ScraperConfigRepository,
    ) -> None:
        """初始化服务。

        Args:
            preference_repository: 用户关注列表仓库
            scraper_config_repository: 抓取配置仓库
        """
        self._pref_repo = preference_repository
        self._scraper_repo = scraper_config_repository

    async def initialize_user_follows(self, user_id: int) -> None:
        """为用户初始化关注列表。

        从当前所有启用的 scraper_follows 复制到用户的 twitter_follows。
        如果用户已有关注列表，则跳过。

        Args:
            user_id: 用户 ID
        """
        # 检查是否已初始化
        if await self._pref_repo.user_has_follows(user_id):
            logger.debug(f"用户 {user_id} 已有关注列表，跳过初始化")
            return

        # 获取所有启用的抓取账号
        scraper_follows = await self._scraper_repo.get_active_follows()
        usernames = [f.username for f in scraper_follows]

        if not usernames:
            logger.debug("没有可用的抓取账号")
            return

        # 批量创建关注记录
        await self._pref_repo.batch_create_follows(
            user_id=user_id,
            usernames=usernames,
        )

        logger.info(f"为用户 {user_id} 初始化关注列表，共 {len(usernames)} 个账号")

    async def add_follow(
        self,
        user_id: int,
        username: str,
    ) -> TwitterFollow:
        """添加/恢复关注。

        验证 username 是否在 scraper_follows 中，如果是则添加到 twitter_follows。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名

        Returns:
            TwitterFollow: 创建的关注记录

        Raises:
            NotFoundError: 如果账号不在抓取列表中
        """
        # 验证账号在抓取列表中
        is_valid = await self._scraper_repo.is_username_in_follows(
            username=username,
            active_only=True,
        )

        if not is_valid:
            raise NotFoundError(
                f"该账号 '@{username}' 不在平台抓取列表中，请联系管理员添加"
            )

        # 创建关注记录
        result = await self._pref_repo.create_follow(
            user_id=user_id,
            username=username,
        )

        logger.info(f"用户 {user_id} 添加关注: {username}")
        return result

    async def remove_follow(
        self,
        user_id: int,
        username: str,
    ) -> None:
        """移除关注。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名

        Raises:
            NotFoundError: 如果关注记录不存在
        """
        # 先检查关注是否存在
        follow = await self._pref_repo.get_follow_by_username(user_id, username)
        if follow is None:
            raise NotFoundError(f"关注记录 '@{username}' 不存在")

        await self._pref_repo.delete_follow(user_id, username)
        logger.info(f"用户 {user_id} 移除关注: {username}")

    async def get_follows(
        self,
        user_id: int,
    ) -> list[TwitterFollow]:
        """查询关注列表。

        返回用户的所有关注记录，按创建时间倒序。

        Args:
            user_id: 用户 ID

        Returns:
            list[TwitterFollow]: 关注记录列表
        """
        return await self._pref_repo.get_follows_by_user(user_id)
