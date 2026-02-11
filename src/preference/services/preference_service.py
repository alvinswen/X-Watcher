"""PreferenceService - 用户偏好管理服务。

协调用户偏好配置的业务逻辑。
"""

import logging
from typing import TYPE_CHECKING

from src.preference.domain.models import (
    FilterType,
    SortType,
    TwitterFollow,
    FilterRule,
)
from src.preference.infrastructure.preference_repository import (
    PreferenceRepository,
    NotFoundError,
)
from src.preference.infrastructure.scraper_config_repository import (
    ScraperConfigRepository,
)

if TYPE_CHECKING:
    from src.preference.services.relevance_service import RelevanceService
    from src.scraper.domain.models import Tweet
    from src.scraper.infrastructure.repository import TweetRepository

logger = logging.getLogger(__name__)


class PreferenceService:
    """用户偏好管理服务。

    管理用户的关注列表、过滤规则和排序偏好。
    """

    def __init__(
        self,
        preference_repository: PreferenceRepository,
        scraper_config_repository: ScraperConfigRepository,
        relevance_service: "RelevanceService | None" = None,
    ) -> None:
        """初始化服务。

        Args:
            preference_repository: 用户偏好仓库
            scraper_config_repository: 抓取配置仓库
            relevance_service: 相关性计算服务（可选）
        """
        self._pref_repo = preference_repository
        self._scraper_repo = scraper_config_repository
        self._relevance_service = relevance_service

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
            default_priority=5,
        )

        logger.info(f"为用户 {user_id} 初始化关注列表，共 {len(usernames)} 个账号")

    async def add_follow(
        self,
        user_id: int,
        username: str,
        priority: int = 5,
    ) -> TwitterFollow:
        """添加/恢复关注。

        验证 username 是否在 scraper_follows 中，如果是则添加到 twitter_follows。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名
            priority: 优先级（1-10，默认 5）

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
            priority=priority,
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
        sort_by: SortType | None = None,
    ) -> list[TwitterFollow]:
        """查询关注列表。

        Args:
            user_id: 用户 ID
            sort_by: 排序方式（可选）

        Returns:
            list[TwitterFollow]: 关注记录列表
        """
        follows = await self._pref_repo.get_follows_by_user(user_id)

        if sort_by == SortType.PRIORITY:
            # 按优先级降序排序
            follows = sorted(follows, key=lambda f: f.priority, reverse=True)

        return follows

    async def update_priority(
        self,
        user_id: int,
        username: str,
        priority: int,
    ) -> TwitterFollow:
        """更新关注优先级。

        Args:
            user_id: 用户 ID
            username: Twitter 用户名
            priority: 新优先级（1-10）

        Returns:
            TwitterFollow: 更新后的关注记录

        Raises:
            NotFoundError: 如果关注记录不存在
        """
        result = await self._pref_repo.update_follow_priority(
            user_id=user_id,
            username=username,
            priority=priority,
        )
        logger.info(f"用户 {user_id} 更新 {username} 优先级为 {priority}")
        return result

    async def add_filter(
        self,
        user_id: int,
        filter_type: FilterType,
        value: str,
    ) -> FilterRule:
        """添加过滤规则。

        Args:
            user_id: 用户 ID
            filter_type: 过滤类型
            value: 过滤值

        Returns:
            FilterRule: 创建的过滤规则
        """
        result = await self._pref_repo.create_filter(
            user_id=user_id,
            filter_type=filter_type,
            value=value,
        )
        logger.info(f"用户 {user_id} 添加过滤规则: {filter_type.value}={value}")
        return result

    async def remove_filter(
        self,
        user_id: int,
        rule_id: str,
    ) -> None:
        """移除过滤规则。

        Args:
            user_id: 用户 ID
            rule_id: 规则 ID（UUID）

        Raises:
            NotFoundError: 如果过滤规则不存在
        """
        # 验证规则属于该用户
        rule = await self._pref_repo.get_filter_by_id(rule_id)
        if rule is None:
            raise NotFoundError(f"过滤规则 '{rule_id}' 不存在")
        if rule.user_id != user_id:
            raise NotFoundError(f"过滤规则 '{rule_id}' 不存在")

        await self._pref_repo.delete_filter(rule_id)
        logger.info(f"用户 {user_id} 移除过滤规则: {rule_id}")

    async def get_filters(
        self,
        user_id: int,
    ) -> list[FilterRule]:
        """查询过滤规则。

        Args:
            user_id: 用户 ID

        Returns:
            list[FilterRule]: 过滤规则列表
        """
        return await self._pref_repo.get_filters_by_user(user_id)

    async def get_sorting_preference(
        self,
        user_id: int,
    ) -> SortType:
        """查询排序偏好。

        Args:
            user_id: 用户 ID

        Returns:
            SortType: 排序类型
        """
        value = await self._pref_repo.get_preference(
            user_id=user_id,
            key="sort_type",
        )

        if value is None:
            return SortType.TIME

        try:
            return SortType(value)
        except ValueError:
            logger.warning(f"无效的排序类型值: {value}，使用默认值")
            return SortType.TIME

    async def update_sorting_preference(
        self,
        user_id: int,
        sort_type: SortType,
    ) -> SortType:
        """更新排序偏好。

        Args:
            user_id: 用户 ID
            sort_type: 排序类型

        Returns:
            SortType: 更新后的排序类型
        """
        await self._pref_repo.set_preference(
            user_id=user_id,
            key="sort_type",
            value=sort_type.value,
        )
        logger.info(f"用户 {user_id} 更新排序偏好为: {sort_type.value}")
        return sort_type

    async def get_sorted_news(
        self,
        user_id: int,
        sort_type: SortType,
        limit: int = 100,
    ) -> list[dict]:
        """获取排序后的个性化新闻流。

        Args:
            user_id: 用户 ID
            sort_type: 排序类型
            limit: 最大返回数量

        Returns:
            list[dict]: 排序后的推文列表，每项包含:
                - tweet: 推文数据（dict 格式）
                - relevance_score: 相关性分数（仅当 sort=relevance 时）
        """
        # 确保用户已初始化关注列表
        await self.initialize_user_follows(user_id)

        # 获取用户的关注列表
        follows = await self._pref_repo.get_follows_by_user(user_id)
        if not follows:
            return []

        usernames = [f.username for f in follows]

        # 导入 TweetRepository（延迟导入避免循环依赖）
        from src.scraper.infrastructure.repository import TweetRepository

        tweet_repo = TweetRepository(self._pref_repo._session)

        # 获取推文
        tweets: list[Tweet] = await tweet_repo.get_tweets_by_usernames(
            usernames=usernames,
            limit=limit,
        )

        if not tweets:
            return []

        # 应用过滤规则
        filters = await self._pref_repo.get_filters_by_user(user_id)
        filtered_tweets = self._apply_filters(tweets, filters)

        # 根据排序类型排序
        if sort_type == SortType.RELEVANCE and self._relevance_service:
            # 相关性排序
            result = await self._sort_by_relevance(
                filtered_tweets,
                filters,
                limit,
            )
        elif sort_type == SortType.PRIORITY:
            # 优先级排序
            result = self._sort_by_priority(
                filtered_tweets,
                follows,
                limit,
            )
        else:
            # 时间排序（默认）
            result = self._sort_by_time(
                filtered_tweets,
                limit,
            )

        return result

    def _apply_filters(
        self,
        tweets: list["Tweet"],
        filters: list[FilterRule],
    ) -> list["Tweet"]:
        """应用过滤规则。

        Args:
            tweets: 推文列表
            filters: 过滤规则列表

        Returns:
            list[Tweet]: 过滤后的推文列表
        """
        if not filters:
            return tweets

        filtered = []
        for tweet in tweets:
            should_exclude = False

            for rule in filters:
                if rule.filter_type == FilterType.KEYWORD:
                    # 关键词过滤：排除包含关键词的推文
                    if rule.value.lower() in tweet.text.lower():
                        should_exclude = True
                        break
                elif rule.filter_type == FilterType.HASHTAG:
                    # 话题标签过滤
                    hashtag = f"#{rule.value.lower()}"
                    if hashtag in tweet.text.lower():
                        should_exclude = True
                        break
                elif rule.filter_type == FilterType.CONTENT_TYPE:
                    # 内容类型过滤
                    if rule.value == "retweet" and tweet.reference_type:
                        should_exclude = True
                        break
                    if rule.value == "has_media" and tweet.media:
                        should_exclude = True
                        break

            if not should_exclude:
                filtered.append(tweet)

        return filtered

    async def _sort_by_relevance(
        self,
        tweets: list["Tweet"],
        filters: list[FilterRule],
        limit: int,
    ) -> list[dict]:
        """按相关性排序。

        Args:
            tweets: 推文列表
            filters: 过滤规则列表（用于提取关键词）
            limit: 最大返回数量

        Returns:
            list[dict]: 包含推文和相关性分数的列表
        """
        # 提取关键词用于相关性计算
        keywords = [
            f.value for f in filters
            if f.filter_type == FilterType.KEYWORD
        ]

        # 计算相关性分数并排序
        tweets_with_score = []
        for tweet in tweets:
            score = await self._relevance_service.calculate_relevance(
                tweet=tweet,
                keywords=keywords,
            )
            tweets_with_score.append((tweet, score))

        # 按相关性分数降序排序
        tweets_with_score.sort(key=lambda x: x[1], reverse=True)

        # 转换为返回格式并限制数量
        return [
            {
                "tweet": tweet.model_dump(),
                "relevance_score": score,
            }
            for tweet, score in tweets_with_score[:limit]
        ]

    def _sort_by_priority(
        self,
        tweets: list["Tweet"],
        follows: list[TwitterFollow],
        limit: int,
    ) -> list[dict]:
        """按优先级排序。

        按作者优先级分组排序，同优先级内按时间排序。

        Args:
            tweets: 推文列表
            follows: 关注列表（包含优先级）
            limit: 最大返回数量

        Returns:
            list[dict]: 包含推文的列表
        """
        # 创建用户名到优先级的映射
        priority_map = {f.username: f.priority for f in follows}

        # 排序：先按优先级降序，同优先级内按时间倒序
        sorted_tweets = sorted(
            tweets,
            key=lambda t: (
                -priority_map.get(t.author_username, 5),  # 优先级降序
                -t.created_at.timestamp(),  # 时间倒序
            ),
        )

        # 转换为返回格式并限制数量
        return [
            {
                "tweet": tweet.model_dump(),
                "relevance_score": None,
            }
            for tweet in sorted_tweets[:limit]
        ]

    def _sort_by_time(
        self,
        tweets: list["Tweet"],
        limit: int,
    ) -> list[dict]:
        """按时间排序。

        Args:
            tweets: 推文列表
            limit: 最大返回数量

        Returns:
            list[dict]: 包含推文的列表
        """
        # 按时间倒序排序（最新的在前）
        sorted_tweets = sorted(
            tweets,
            key=lambda t: t.created_at,
            reverse=True,
        )

        # 转换为返回格式并限制数量
        return [
            {
                "tweet": tweet.model_dump(),
                "relevance_score": None,
            }
            for tweet in sorted_tweets[:limit]
        ]
