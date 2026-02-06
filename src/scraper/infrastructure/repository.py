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

    async def save_tweets(self, tweets: list[Tweet]) -> SaveResult:
        """批量保存推文。

        基于 tweet_id 唯一约束实现去重逻辑。

        Args:
            tweets: 推文列表

        Returns:
            SaveResult: 保存结果，包含成功、跳过和错误数量
        """
        success_count = 0
        skipped_count = 0
        error_count = 0

        for tweet in tweets:
            try:
                # 检查是否已存在
                exists = await self.tweet_exists(tweet.tweet_id)
                if exists:
                    skipped_count += 1
                    continue

                # 创建 ORM 实例
                orm_tweet = TweetOrm.from_domain(tweet)

                # 保存到数据库
                self._session.add(orm_tweet)
                await self._session.flush()

                success_count += 1

            except Exception as e:
                # 记录错误但继续处理其他推文
                logger.error(f"保存推文 {tweet.tweet_id} 失败: {e}")
                error_count += 1

        return SaveResult(
            success_count=success_count,
            skipped_count=skipped_count,
            error_count=error_count,
        )

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
