"""ScraperConfigService - 平台抓取配置服务。

协调平台级抓取账号配置的业务逻辑。
"""

import logging

from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
    NotFoundError,
    DuplicateError,
)

logger = logging.getLogger(__name__)


class ScraperConfigService:
    """平台抓取配置服务。

    管理员维护的平台级 Twitter 关注列表的业务逻辑层。
    """

    def __init__(self, repository: ScraperConfigRepository) -> None:
        """初始化服务。

        Args:
            repository: 抓取配置仓库
        """
        self._repository = repository

    async def add_scraper_follow(
        self,
        username: str,
        reason: str,
        added_by: str,
    ) -> ScraperFollow:
        """添加抓取账号。

        Args:
            username: Twitter 用户名
            reason: 添加理由
            added_by: 添加人标识

        Returns:
            ScraperFollow: 创建的抓取账号

        Raises:
            DuplicateError: 如果用户名已存在
        """
        logger.info(f"添加抓取账号: username={username}, added_by={added_by}")
        return await self._repository.create_scraper_follow(
            username=username,
            reason=reason,
            added_by=added_by,
        )

    async def get_all_follows(
        self,
        include_inactive: bool = False,
    ) -> list[ScraperFollow]:
        """获取所有抓取账号。

        Args:
            include_inactive: 是否包含禁用的账号

        Returns:
            list[ScraperFollow]: 抓取账号列表
        """
        return await self._repository.get_all_follows(
            include_inactive=include_inactive,
        )

    async def update_follow(
        self,
        username: str,
        reason: str | None = None,
        is_active: bool | None = None,
    ) -> ScraperFollow:
        """更新抓取账号。

        Args:
            username: Twitter 用户名
            reason: 新的添加理由（可选）
            is_active: 是否启用（可选）

        Returns:
            ScraperFollow: 更新后的抓取账号

        Raises:
            NotFoundError: 如果账号不存在
        """
        logger.info(f"更新抓取账号: username={username}")
        return await self._repository.update_scraper_follow(
            username=username,
            reason=reason,
            is_active=is_active,
        )

    async def deactivate_follow(
        self,
        username: str,
    ) -> None:
        """禁用抓取账号（软删除）。

        Args:
            username: Twitter 用户名

        Raises:
            NotFoundError: 如果账号不存在
        """
        logger.info(f"禁用抓取账号: username={username}")
        await self._repository.deactivate_follow(username)

    async def is_username_in_follows(
        self,
        username: str,
        active_only: bool = True,
    ) -> bool:
        """检查用户名是否在抓取列表中。

        Args:
            username: Twitter 用户名
            active_only: 是否只检查启用的账号

        Returns:
            bool: 如果用户名存在返回 True，否则返回 False
        """
        return await self._repository.is_username_in_follows(
            username=username,
            active_only=active_only,
        )
