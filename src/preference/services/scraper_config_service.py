"""ScraperConfigService - 平台抓取配置服务。

协调平台级抓取账号配置的业务逻辑。
"""

import logging
from datetime import datetime

from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.follow_store import (
    DuplicateError,
    FollowStore,
    NotFoundError,
)

logger = logging.getLogger(__name__)


class ScraperConfigService:
    """平台抓取配置服务。

    管理员维护的平台级 Twitter 关注列表的业务逻辑层。
    """

    def __init__(self, repository: FollowStore) -> None:
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
        manual_limit: int | None = None,
        brief_intro: str | None = None,
    ) -> ScraperFollow:
        """更新抓取账号。

        Args:
            username: Twitter 用户名
            reason: 新的添加理由（可选）
            is_active: 是否启用（可选）
            manual_limit: 手动推文数量限制（0 清除，正整数设置，None 不修改）
            brief_intro: 极简介绍（None 不修改，空字符串清空）

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
            manual_limit=manual_limit,
            brief_intro=brief_intro,
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


async def get_tweet_time_ranges(
    usernames: list[str],
) -> dict[str, tuple[datetime | None, datetime | None, int]]:
    """批量查询各账号的推文时间范围(earliest, latest, count)，含无数据账号兜底。

    封装 REST ``get_follows_tweet_time_range`` 与 MCP ``get_follow_accounts_info``
    (info_type=tweet_time_range/stats)三处此前重复的"判空 → 调用
    tweet_time_range 仓储方法 → 按 username.lower() 三元组拆包并兜底"样板
    (CHG-032 目标 2)，各端仍各自负责把返回值组装成各自的响应结构
    (Pydantic 模型 / dict)，对外契约不变。

    Args:
        usernames: 待查询的用户名列表(保留调用方原始大小写作为返回 dict 的 key)

    Returns:
        {username: (earliest_tweet_at, latest_tweet_at, tweet_count)}，
        无推文数据的账号兜底为 (None, None, 0)；usernames 为空时返回 {}
    """
    if not usernames:
        return {}

    from src.data_layer.provider import get_scraper_stats_repo

    rows = await get_scraper_stats_repo().tweet_time_range(usernames)
    return {
        u: (
            rows[u.lower()][0] if u.lower() in rows else None,
            rows[u.lower()][1] if u.lower() in rows else None,
            rows[u.lower()][2] if u.lower() in rows else 0,
        )
        for u in usernames
    }
