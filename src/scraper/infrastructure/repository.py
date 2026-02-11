"""推文数据仓库。

实现推文的数据库 CRUD 操作和去重逻辑。
"""

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.infrastructure.models import TweetOrm

if TYPE_CHECKING:
    from returns.result import Result

logger = logging.getLogger(__name__)


class TweetRepository:
    """推文数据仓库。

    负责推文数据的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化仓库。

        Args:
            session: 异步数据库会话
        """
        self._session = session

    async def save_tweets(
        self,
        tweets: list[Tweet],
        early_stop_threshold: int = 5,
    ) -> SaveResult:
        """批量保存推文（支持批量去重和提前终止）。

        基于 tweet_id 唯一约束实现去重逻辑。使用批量查询替代逐条检查，
        并在连续遇到已存在推文时提前终止处理。

        Args:
            tweets: 推文列表（应按时间倒序排列，即最新推文在前）
            early_stop_threshold: 连续已存在推文阈值，达到后提前终止。
                设为 0 则禁用提前终止。

        Returns:
            SaveResult: 保存结果，包含成功、跳过和错误数量
        """
        if not tweets:
            return SaveResult(success_count=0, skipped_count=0, error_count=0)

        # 批量去重：一次查询获取所有已存在的 tweet_id
        existing_ids = await self.batch_check_exists(
            [t.tweet_id for t in tweets]
        )

        success_count = 0
        skipped_count = 0
        error_count = 0
        consecutive_existing = 0

        for tweet in tweets:
            if tweet.tweet_id in existing_ids:
                skipped_count += 1
                consecutive_existing += 1

                # 提前终止：连续遇到已存在推文超过阈值
                if early_stop_threshold > 0 and consecutive_existing >= early_stop_threshold:
                    remaining = len(tweets) - success_count - skipped_count
                    skipped_count += remaining
                    logger.info(
                        "连续 %d 条推文已存在，提前终止（跳过剩余 %d 条）",
                        consecutive_existing,
                        remaining,
                    )
                    break
                continue

            # 遇到新推文，重置连续计数
            consecutive_existing = 0

            try:
                orm_tweet = TweetOrm.from_domain(tweet)
                self._session.add(orm_tweet)
                await self._session.flush()
                success_count += 1
            except Exception as e:
                logger.error(f"保存推文 {tweet.tweet_id} 失败: {e}")
                error_count += 1

        return SaveResult(
            success_count=success_count,
            skipped_count=skipped_count,
            error_count=error_count,
        )

    async def batch_check_exists(self, tweet_ids: list[str]) -> set[str]:
        """批量检查推文是否已存在。

        Args:
            tweet_ids: 推文 ID 列表

        Returns:
            set[str]: 已存在的推文 ID 集合
        """
        if not tweet_ids:
            return set()

        stmt = select(TweetOrm.tweet_id).where(
            TweetOrm.tweet_id.in_(tweet_ids)
        )
        result = await self._session.execute(stmt)
        return {row[0] for row in result.all()}

    async def tweet_exists(self, tweet_id: str) -> bool:
        """检查推文是否已存在。

        Args:
            tweet_id: 推文 ID

        Returns:
            bool: 如果推文存在返回 True，否则返回 False
        """
        stmt = select(TweetOrm.tweet_id).where(TweetOrm.tweet_id == tweet_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_tweets_by_author(
        self,
        author_username: str,
        limit: int = 100,
    ) -> list[Tweet]:
        """按作者查询推文。

        Args:
            author_username: 作者用户名
            limit: 最大返回数量

        Returns:
            list[Tweet]: 推文列表
        """
        stmt = (
            select(TweetOrm)
            .where(TweetOrm.author_username == author_username)
            .order_by(TweetOrm.created_at.desc())
            .limit(limit)
        )

        result = await self._session.execute(stmt)
        orm_tweets = result.scalars().all()

        return [tweet.to_domain() for tweet in orm_tweets]

    async def get_tweets_by_usernames(
        self,
        usernames: list[str],
        limit: int = 100,
    ) -> list[Tweet]:
        """按用户名列表查询推文。

        Args:
            usernames: 作者用户名列表
            limit: 最大返回数量（默认 100）

        Returns:
            list[Tweet]: 推文列表，按时间倒序排列

        Note:
            如果 usernames 为空列表或 limit 为 0，返回空列表
        """
        # 处理边界条件
        if not usernames or limit <= 0:
            return []

        try:
            stmt = (
                select(TweetOrm)
                .where(TweetOrm.author_username.in_(usernames))
                .order_by(TweetOrm.created_at.desc())
                .limit(limit)
            )

            result = await self._session.execute(stmt)
            orm_tweets = result.scalars().all()

            return [tweet.to_domain() for tweet in orm_tweets]

        except Exception as e:
            logger.error(f"按用户名列表查询推文失败: {e}")
            # 返回空列表而不是抛出异常，保持一致性
            return []
