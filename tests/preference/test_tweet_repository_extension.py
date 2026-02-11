"""TweetRepository 扩展单元测试。

测试按用户名列表查询推文的功能。
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy import select

from src.scraper.infrastructure.models import TweetOrm
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.repository import TweetRepository


class TestGetTweetsByUsernames:
    """测试按用户名列表查询推文。"""

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_empty_list(self, async_session):
        """测试空用户名列表返回空结果。"""
        repo = TweetRepository(async_session)

        tweets = await repo.get_tweets_by_usernames([])

        assert tweets == []

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_no_results(self, async_session):
        """测试没有匹配用户时返回空结果。"""
        repo = TweetRepository(async_session)

        tweets = await repo.get_tweets_by_usernames(["nonexistent1", "nonexistent2"])

        assert tweets == []

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_single_user(self, async_session):
        """查询单个用户的推文。"""
        repo = TweetRepository(async_session)

        # 创建测试推文
        tweet1 = TweetOrm(
            tweet_id="1",
            author_username="karpathy",
            text="AI is amazing",
            created_at=datetime.now(timezone.utc),
        )
        tweet2 = TweetOrm(
            tweet_id="2",
            author_username="karpathy",
            text="Deep learning rules",
            created_at=datetime.now(timezone.utc),
        )
        async_session.add(tweet1)
        async_session.add(tweet2)
        await async_session.flush()

        # 查询
        tweets = await repo.get_tweets_by_usernames(["karpathy"])

        assert len(tweets) == 2
        texts = {t.text for t in tweets}
        assert texts == {"AI is amazing", "Deep learning rules"}

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_multiple_users(self, async_session):
        """测试查询多个用户的推文。"""
        repo = TweetRepository(async_session)

        # 创建测试推文
        tweet1 = TweetOrm(
            tweet_id="1",
            author_username="karpathy",
            text="AI is amazing",
            created_at=datetime.now(timezone.utc),
        )
        tweet2 = TweetOrm(
            tweet_id="2",
            author_username="ylecun",
            text="AI is not just statistics",
            created_at=datetime.now(timezone.utc),
        )
        tweet3 = TweetOrm(
            tweet_id="3",
            author_username="samalt",
            text="OpenAI is great",
            created_at=datetime.now(timezone.utc),
        )
        async_session.add_all([tweet1, tweet2, tweet3])
        await async_session.flush()

        # 查询多个用户
        tweets = await repo.get_tweets_by_usernames(["karpathy", "samalt"])

        assert len(tweets) == 2
        usernames = {t.author_username for t in tweets}
        assert usernames == {"karpathy", "samalt"}

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_with_limit(self, async_session):
        """测试带限制参数的查询。"""
        repo = TweetRepository(async_session)

        # 创建多个推文
        for i in range(10):
            tweet = TweetOrm(
                tweet_id=f"{i}",
                author_username="karpathy",
                text=f"Tweet {i}",
                created_at=datetime.now(timezone.utc),
            )
            async_session.add(tweet)
        await async_session.flush()

        # 限制返回数量
        tweets = await repo.get_tweets_by_usernames(["karpathy"], limit=5)

        assert len(tweets) == 5

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_respects_limit(self, async_session):
        """测试限制参数在多个用户时正确工作。"""
        repo = TweetRepository(async_session)

        # 为不同用户创建推文
        for i, user in enumerate(["user1", "user2", "user3"]):
            for j in range(5):
                tweet = TweetOrm(
                    tweet_id=f"{i}_{j}",
                    author_username=user,
                    text=f"Tweet {j} from {user}",
                    created_at=datetime.now(timezone.utc),
                )
                async_session.add(tweet)
        await async_session.flush()

        # 限制返回数量
        tweets = await repo.get_tweets_by_usernames(["user1", "user2", "user3"], limit=10)

        assert len(tweets) == 10

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_default_limit(self, async_session):
        """测试默认限制为 100。"""
        repo = TweetRepository(async_session)

        # 创建超过 100 条推文
        for i in range(150):
            tweet = TweetOrm(
                tweet_id=f"{i}",
                author_username="karpathy",
                text=f"Tweet {i}",
                created_at=datetime.now(timezone.utc),
            )
            async_session.add(tweet)
        await async_session.flush()

        # 不指定限制，应返回 100 条
        tweets = await repo.get_tweets_by_usernames(["karpathy"])

        assert len(tweets) == 100

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_ordering(self, async_session):
        """测试结果按时间倒序排列。"""
        repo = TweetRepository(async_session)

        # 创建不同时间的推文
        for i in range(5):
            tweet = TweetOrm(
                tweet_id=f"{i}",
                author_username="karpathy",
                text=f"Tweet {i}",
                created_at=datetime(2024, 1, i + 1, 12, 0, 0, tzinfo=timezone.utc),
            )
            async_session.add(tweet)
        await async_session.flush()

        # 查询
        tweets = await repo.get_tweets_by_usernames(["karpathy"])

        # 验证倒序
        assert len(tweets) == 5
        # 第一个应该是日期最新的
        assert tweets[0].created_at.day == 5
        assert tweets[4].created_at.day == 1

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_mixed_results(self, async_session):
        """测试部分用户有推文，部分没有。"""
        repo = TweetRepository(async_session)

        # 只为 karpathy 创建推文
        tweet1 = TweetOrm(
            tweet_id="1",
            author_username="karpathy",
            text="AI tweet",
            created_at=datetime.now(timezone.utc),
        )
        async_session.add(tweet1)
        await async_session.flush()

        # 查询包含有推文和没有推文的用户
        tweets = await repo.get_tweets_by_usernames(["karpathy", "nonexistent", "ylecun"])

        assert len(tweets) == 1
        assert tweets[0].author_username == "karpathy"

    @pytest.mark.asyncio
    async def test_get_tweets_by_usernames_zero_limit(self, async_session):
        """测试限制为 0 时返回空结果。"""
        repo = TweetRepository(async_session)

        # 创建推文
        tweet = TweetOrm(
            tweet_id="1",
            author_username="karpathy",
            text="AI tweet",
            created_at=datetime.now(timezone.utc),
        )
        async_session.add(tweet)
        await async_session.flush()

        # 限制为 0
        tweets = await repo.get_tweets_by_usernames(["karpathy"], limit=0)

        assert tweets == []
