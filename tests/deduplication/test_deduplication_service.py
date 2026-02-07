"""去重服务单元测试。"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database.models import Base
from src.deduplication.domain.detectors import ExactDuplicateDetector, SimilarityDetector
from src.deduplication.domain.models import DeduplicationConfig, DeduplicationType
from src.deduplication.infrastructure.repository import DeduplicationRepository
from src.deduplication.services.deduplication_service import DeduplicationService
from src.scraper.domain.models import Tweet
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
def sample_tweets() -> list[Tweet]:
    """创建示例推文。"""
    now = datetime.now(timezone.utc)
    return [
        Tweet(
            tweet_id="1",
            text="Hello world",
            created_at=now,
            author_username="user1",
        ),
        Tweet(
            tweet_id="2",
            text="Hello world",  # 重复
            created_at=now,
            author_username="user2",
        ),
        Tweet(
            tweet_id="3",
            text="Different content",
            created_at=now,
            author_username="user1",
        ),
        Tweet(
            tweet_id="4",
            text="Hello world",  # 重复
            created_at=now,
            author_username="user3",
        ),
    ]


class TestDeduplicationService:
    """去重服务测试。"""

    @pytest.mark.asyncio
    async def test_deduplicate_tweets_with_duplicates(
        self, session: AsyncSession, sample_tweets: list[Tweet]
    ):
        """测试去重重复推文。"""
        # 先保存推文到数据库
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            session.add(orm)
        await session.commit()

        # 创建服务
        repository = DeduplicationRepository(session)
        service = DeduplicationService(
            repository=repository,
            exact_detector=ExactDuplicateDetector(),
            similarity_detector=SimilarityDetector(),
        )

        # 执行去重
        result = await service.deduplicate_tweets(
            tweet_ids=[t.tweet_id for t in sample_tweets]
        )

        # 验证结果
        assert result.total_tweets == 4
        assert result.exact_duplicate_count == 1
        assert result.affected_tweets == 3  # 1,2,4 被去重
        assert result.preserved_tweets == 2  # 1(代表),3
        assert result.elapsed_seconds >= 0

    @pytest.mark.asyncio
    async def test_deduplicate_tweets_with_empty_list(
        self, session: AsyncSession
    ):
        """测试空列表。"""
        repository = DeduplicationRepository(session)
        service = DeduplicationService(repository=repository)

        result = await service.deduplicate_tweets([])

        assert result.total_tweets == 0
        assert result.exact_duplicate_count == 0
        assert result.similar_content_count == 0

    @pytest.mark.asyncio
    async def test_deduplicate_tweets_with_config(
        self, session: AsyncSession, sample_tweets: list[Tweet]
    ):
        """测试使用配置。"""
        # 保存推文
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            session.add(orm)
        await session.commit()

        repository = DeduplicationRepository(session)
        service = DeduplicationService(repository=repository)

        # 使用自定义配置
        config = DeduplicationConfig(
            enable_exact_duplicate=True,
            enable_similar_content=False,  # 禁用相似度检测
        )

        result = await service.deduplicate_tweets(
            tweet_ids=[t.tweet_id for t in sample_tweets],
            config=config,
        )

        assert result.exact_duplicate_count == 1
        assert result.similar_content_count == 0

    @pytest.mark.asyncio
    async def test_deduplicate_idempotent(
        self, session: AsyncSession, sample_tweets: list[Tweet]
    ):
        """测试幂等性：已去重的推文不会重复处理。"""
        # 保存推文
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            session.add(orm)
        await session.commit()

        repository = DeduplicationRepository(session)
        service = DeduplicationService(repository=repository)

        # 第一次去重
        result1 = await service.deduplicate_tweets(
            tweet_ids=[t.tweet_id for t in sample_tweets]
        )

        # 第二次去重（应该跳过已去重的推文）
        result2 = await service.deduplicate_tweets(
            tweet_ids=[t.tweet_id for t in sample_tweets]
        )

        # 第二次应该没有新的去重组
        assert result2.exact_duplicate_count == 0
        assert result2.similar_content_count == 0


class TestDeduplicationRepository:
    """去重仓库测试。"""

    @pytest.mark.asyncio
    async def test_save_and_get_group(self, session: AsyncSession):
        """测试保存和获取去重组。"""
        from src.deduplication.domain.models import DeduplicationGroup

        repository = DeduplicationRepository(session)

        group = DeduplicationGroup(
            group_id="test-group-1",
            representative_tweet_id="1",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["1", "2", "3"],
            created_at=datetime.now(timezone.utc),
        )

        await repository.save_groups([group])
        await session.commit()

        # 获取组
        retrieved = await repository.get_group("test-group-1")
        assert retrieved is not None
        assert retrieved.group_id == "test-group-1"
        assert retrieved.representative_tweet_id == "1"
        assert retrieved.deduplication_type == DeduplicationType.exact_duplicate
        assert retrieved.tweet_ids == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_find_by_tweet(self, session: AsyncSession):
        """测试根据推文查找去重组。"""
        from src.deduplication.domain.models import DeduplicationGroup

        repository = DeduplicationRepository(session)

        # 先保存推文
        for i in range(3):
            tweet = TweetOrm(
                tweet_id=str(i),
                text=f"Tweet {i}",
                created_at=datetime.now(timezone.utc),
                author_username="user",
            )
            session.add(tweet)
        await session.commit()

        group = DeduplicationGroup(
            group_id="test-group-2",
            representative_tweet_id="0",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["0", "1", "2"],
            created_at=datetime.now(timezone.utc),
        )

        await repository.save_groups([group])
        await session.commit()

        # 查找
        found = await repository.find_by_tweet("1")
        assert found is not None
        assert found.group_id == "test-group-2"

    @pytest.mark.asyncio
    async def test_delete_group(self, session: AsyncSession):
        """测试删除去重组。"""
        from src.deduplication.domain.models import DeduplicationGroup

        repository = DeduplicationRepository(session)

        # 先保存推文
        tweet = TweetOrm(
            tweet_id="1",
            text="Tweet 1",
            created_at=datetime.now(timezone.utc),
            author_username="user",
            deduplication_group_id="test-group-3",
        )
        session.add(tweet)
        await session.commit()

        group = DeduplicationGroup(
            group_id="test-group-3",
            representative_tweet_id="1",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["1"],
            created_at=datetime.now(timezone.utc),
        )

        await repository.save_groups([group])
        await session.commit()

        # 删除
        await repository.delete_group("test-group-3")
        await session.commit()

        # 验证删除
        found = await repository.get_group("test-group-3")
        assert found is None
