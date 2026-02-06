"""TweetRepository 单元测试。

测试推文数据仓库的 CRUD 操作和去重逻辑。
"""

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import clear_mappers

from src.database.models import Base
from src.scraper.domain.models import Media, ReferenceType, SaveResult, Tweet
from src.scraper.infrastructure.models import TweetOrm


@pytest.fixture
async def async_session_maker():
    """创建测试用的异步会话工厂。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def session(async_session_maker):
    """创建测试用的数据库会话。"""
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def sample_tweet() -> Tweet:
    """创建示例推文。"""
    return Tweet(
        tweet_id="1234567890",
        text="This is a test tweet.",
        created_at=datetime.now(timezone.utc),
        author_username="testuser",
        author_display_name="Test User",
    )


@pytest.fixture
def sample_tweet_with_media() -> Tweet:
    """创建带媒体的示例推文。"""
    return Tweet(
        tweet_id="0987654321",
        text="This is a tweet with media.",
        created_at=datetime.now(timezone.utc),
        author_username="testuser",
        author_display_name="Test User",
        media=[
            Media(
                media_key="media_123",
                type="photo",
                url="https://example.com/image.jpg",
                width=800,
                height=600,
            )
        ],
    )


@pytest.fixture
def sample_tweet_with_reference() -> Tweet:
    """创建带引用的示例推文。"""
    return Tweet(
        tweet_id="1111222233",
        text="This is a retweet.",
        created_at=datetime.now(timezone.utc),
        author_username="testuser",
        author_display_name="Test User",
        referenced_tweet_id="1234567890",
        reference_type=ReferenceType.retweeted,
    )


class TestTweetRepository:
    """TweetRepository 测试类。"""

    @pytest.mark.asyncio
    async def test_save_single_tweet(self, session: AsyncSession, sample_tweet: Tweet):
        """测试保存单条推文。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        result = await repo.save_tweets([sample_tweet])

        assert result.success_count == 1
        assert result.skipped_count == 0
        assert result.error_count == 0

        # 验证数据库中的记录
        stmt = TweetOrm.tweet_id == sample_tweet.tweet_id
        from sqlalchemy import select

        orm_tweet = await session.execute(select(TweetOrm).where(stmt))
        tweet = orm_tweet.scalar_one_or_none()

        assert tweet is not None
        assert tweet.tweet_id == sample_tweet.tweet_id
        assert tweet.text == sample_tweet.text
        assert tweet.author_username == sample_tweet.author_username

    @pytest.mark.asyncio
    async def test_save_duplicate_tweet_skipped(
        self, session: AsyncSession, sample_tweet: Tweet
    ):
        """测试保存重复推文时跳过。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        # 第一次保存
        result1 = await repo.save_tweets([sample_tweet])
        assert result1.success_count == 1

        # 第二次保存（应该跳过）
        result2 = await repo.save_tweets([sample_tweet])
        assert result2.success_count == 0
        assert result2.skipped_count == 1
        assert result2.error_count == 0

    @pytest.mark.asyncio
    async def test_save_multiple_tweets(self, session: AsyncSession):
        """测试批量保存多条推文。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        tweets = [
            Tweet(
                tweet_id=str(i),
                text=f"Tweet {i}",
                created_at=datetime.now(timezone.utc),
                author_username="testuser",
                author_display_name="Test User",
            )
            for i in range(5)
        ]

        result = await repo.save_tweets(tweets)

        assert result.success_count == 5
        assert result.skipped_count == 0
        assert result.error_count == 0

    @pytest.mark.asyncio
    async def test_save_tweet_with_media(
        self, session: AsyncSession, sample_tweet_with_media: Tweet
    ):
        """测试保存带媒体的推文。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        result = await repo.save_tweets([sample_tweet_with_media])

        assert result.success_count == 1

        # 验证媒体数据
        from sqlalchemy import select

        stmt = TweetOrm.tweet_id == sample_tweet_with_media.tweet_id
        orm_tweet = await session.execute(select(TweetOrm).where(stmt))
        tweet = orm_tweet.scalar_one_or_none()

        assert tweet is not None
        assert tweet.media is not None
        assert len(tweet.media) == 1
        assert tweet.media[0]["type"] == "photo"
        assert tweet.media[0]["url"] == "https://example.com/image.jpg"

    @pytest.mark.asyncio
    async def test_save_tweet_with_reference(
        self, session: AsyncSession, sample_tweet_with_reference: Tweet
    ):
        """测试保存带引用的推文。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        result = await repo.save_tweets([sample_tweet_with_reference])

        assert result.success_count == 1

        # 验证引用数据
        from sqlalchemy import select

        stmt = TweetOrm.tweet_id == sample_tweet_with_reference.tweet_id
        orm_tweet = await session.execute(select(TweetOrm).where(stmt))
        tweet = orm_tweet.scalar_one_or_none()

        assert tweet is not None
        assert tweet.referenced_tweet_id == "1234567890"
        assert tweet.reference_type == "retweeted"

    @pytest.mark.asyncio
    async def test_tweet_exists(self, session: AsyncSession, sample_tweet: Tweet):
        """测试检查推文是否存在。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        # 推文不存在
        exists_before = await repo.tweet_exists(sample_tweet.tweet_id)
        assert exists_before is False

        # 保存推文
        await repo.save_tweets([sample_tweet])

        # 推文存在
        exists_after = await repo.tweet_exists(sample_tweet.tweet_id)
        assert exists_after is True

    @pytest.mark.asyncio
    async def test_get_tweets_by_author(self, session: AsyncSession):
        """测试按作者查询推文。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        # 保存多个用户的推文
        tweets = [
            Tweet(
                tweet_id="1",
                text="Tweet 1",
                created_at=datetime.now(timezone.utc),
                author_username="user1",
            ),
            Tweet(
                tweet_id="2",
                text="Tweet 2",
                created_at=datetime.now(timezone.utc),
                author_username="user1",
            ),
            Tweet(
                tweet_id="3",
                text="Tweet 3",
                created_at=datetime.now(timezone.utc),
                author_username="user2",
            ),
        ]

        await repo.save_tweets(tweets)

        # 查询 user1 的推文
        user1_tweets = await repo.get_tweets_by_author("user1")
        assert len(user1_tweets) == 2

        # 查询 user2 的推文
        user2_tweets = await repo.get_tweets_by_author("user2")
        assert len(user2_tweets) == 1

        # 查询不存在的用户
        user3_tweets = await repo.get_tweets_by_author("user3")
        assert len(user3_tweets) == 0

    @pytest.mark.asyncio
    async def test_get_tweets_by_author_with_limit(self, session: AsyncSession):
        """测试带限制的按作者查询。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        # 保存 5 条推文
        tweets = [
            Tweet(
                tweet_id=str(i),
                text=f"Tweet {i}",
                created_at=datetime.now(timezone.utc),
                author_username="user1",
            )
            for i in range(5)
        ]

        await repo.save_tweets(tweets)

        # 查询限制 3 条
        result = await repo.get_tweets_by_author("user1", limit=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_save_mixed_new_and_existing_tweets(
        self, session: AsyncSession
    ):
        """测试保存混合新推文和已存在推文。"""
        from src.scraper.infrastructure.repository import TweetRepository

        repo = TweetRepository(session)

        # 先保存一条推文
        existing_tweet = Tweet(
            tweet_id="1",
            text="Existing tweet",
            created_at=datetime.now(timezone.utc),
            author_username="user1",
        )
        await repo.save_tweets([existing_tweet])

        # 保存混合推文（一条已存在，两条新推文）
        tweets = [
            existing_tweet,
            Tweet(
                tweet_id="2",
                text="New tweet 2",
                created_at=datetime.now(timezone.utc),
                author_username="user1",
            ),
            Tweet(
                tweet_id="3",
                text="New tweet 3",
                created_at=datetime.now(timezone.utc),
                author_username="user1",
            ),
        ]

        result = await repo.save_tweets(tweets)

        assert result.success_count == 2
        assert result.skipped_count == 1
        assert result.error_count == 0
