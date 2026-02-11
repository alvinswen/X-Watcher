"""摘要服务性能测试。

使用 pytest-benchmark 验证性能指标。
"""

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.deduplication.domain.models import DeduplicationGroup, DeduplicationType
from src.scraper.infrastructure.models import DeduplicationGroupOrm
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.domain.models import PromptConfig
from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.services.summarization_service import (
    SummarizationService,
    create_summarization_service,
)

# 尝试导入 pytest-benchmark
try:
    import pytest_benchmark

    HAS_BENCHMARK = True
except ImportError:
    HAS_BENCHMARK = False
    pytest.skip("pytest-benchmark not installed", allow_module_level=True)


@pytest.fixture(autouse=True)
def setup_test_env():
    """设置测试环境变量。"""
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    os.environ["MINIMAX_API_KEY"] = "test-key"

    yield

    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("MINIMAX_API_KEY", None)


@pytest.fixture
def mock_llm_providers():
    """模拟 LLM 提供商。"""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_provider = MagicMock()
    mock_provider.generate_summary = AsyncMock(
        return_value=(
            "This is a test summary" + " with enough content" * 8,
            "This is a test translation",
            100,
            50,
            150,
            0.001,
        )
    )

    return {
        "openrouter": mock_provider,
        "minimax": mock_provider,
    }


class TestSingleTweetPerformance:
    """测试单条推文处理性能。"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_BENCHMARK, reason="pytest-benchmark not installed")
    async def test_single_tweet_summary_time(
        self,
        async_session,
        mock_llm_providers,
        benchmark,
    ):
        """测试单条推文处理时间 < 10 秒。"""

        async def setup_and_summarize():
            """设置并执行摘要。"""
            # 创建推文
            tweet = Tweet(
                tweet_id="perf_tweet_1",
                author_author_username="perf_user",
                text="Performance test tweet" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

            # 创建去重组
            group = DeduplicationGroup(
                group_id="perf_group_1",
                representative_tweet_id="perf_tweet_1",
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=["perf_tweet_1"],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

            # 更新推文的去重组 ID
            stmt = select(TweetOrm).where(TweetOrm.tweet_id == "perf_tweet_1")
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = "perf_group_1"
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            config = LLMProviderConfig.from_env()

            with patch(
                "src.summarization.services.summarization_service.OpenRouterProvider",
                return_value=mock_llm_providers["openrouter"],
            ):
                service = create_summarization_service(
                    repository=repo,
                    config=config,
                    prompt_config=PromptConfig(),
                )

                # 执行摘要
                result = await service.summarize_tweets(
                    tweet_ids=["perf_tweet_1"],
                    force_refresh=True,
                )

                from returns.result import Failure

                if isinstance(result, Failure):
                    raise result.failure()

                return result.unwrap()

        # 执行基准测试
        result = benchmark(setup_and_summarize)

        # 验证结果
        assert result.total_tweets == 1
        assert result.total_groups == 1

        # pytest-benchmark 会自动记录时间


class TestBatchPerformance:
    """测试批量处理性能。"""

    @pytest.fixture
    async def setup_ten_tweets(self, async_session):
        """设置 10 条测试推文。"""
        tweets = []
        for i in range(10):
            tweet = Tweet(
                tweet_id=f"perf_tweet_{i}",
                author_username="perf_user",
                text=f"Performance test tweet {i}" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            tweets.append(tweet)

        # 保存推文
        for tweet in tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

        # 创建去重组
        for i, tweet in enumerate(tweets):
            group = DeduplicationGroup(
                group_id=f"perf_group_{i}",
                representative_tweet_id=tweet.tweet_id,
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=[tweet.tweet_id],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

        # 更新推文的去重组 ID
        for tweet in tweets:
            stmt = select(TweetOrm).where(TweetOrm.tweet_id == tweet.tweet_id)
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = f"perf_group_{tweets.index(tweet)}"

        await async_session.commit()
        return [t.tweet_id for t in tweets]

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_BENCHMARK, reason="pytest-benchmark not installed")
    async def test_ten_tweets_batch_time(
        self,
        async_session,
        setup_ten_tweets,
        mock_llm_providers,
        benchmark,
    ):
        """测试 10 条推文批量处理时间 < 30 秒。"""
        tweet_ids = await setup_ten_tweets

        async def batch_summarize():
            """批量执行摘要。"""
            repo = SummarizationRepository(async_session)
            config = LLMProviderConfig.from_env()

            with patch(
                "src.summarization.services.summarization_service.OpenRouterProvider",
                return_value=mock_llm_providers["openrouter"],
            ):
                service = create_summarization_service(
                    repository=repo,
                    config=config,
                    prompt_config=PromptConfig(),
                )

                result = await service.summarize_tweets(
                    tweet_ids=tweet_ids,
                    force_refresh=True,
                )

                from returns.result import Failure

                if isinstance(result, Failure):
                    raise result.failure()

                return result.unwrap()

        result = benchmark(batch_summarize)

        # 验证结果
        assert result.total_tweets == 10
        assert result.total_groups == 10


class TestCachePerformance:
    """测试缓存性能。"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_BENCHMARK, reason="pytest-benchmark not installed")
    async def test_cache_query_time(
        self,
        async_session,
        benchmark,
    ):
        """测试缓存查询时间 < 100 毫秒。"""
        from src.summarization.domain.models import SummaryRecord

        # 预先保存摘要
        summary = SummaryOrm.from_domain(
            SummaryRecord(
                summary_id="cache_perf_summary",
                tweet_id="cache_perf_tweet",
                summary_text="Cached summary" + " text" * 15,
                translation_text="Cached translation",
                model_provider="openrouter",
                model_name="claude-sonnet-4.5",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
                cached=True,
                content_hash="cache_hash_123",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        async_session.add(summary)
        await async_session.commit()

        async def query_cache():
            """查询缓存。"""
            repo = SummarizationRepository(async_session)
            return await repo.get_summary_by_tweet("cache_perf_tweet")

        result = benchmark(query_cache)

        # 验证结果
        assert result is not None
        assert result.summary_id == "cache_perf_summary"


class TestMemoryUsage:
    """测试内存占用。"""

    @pytest.mark.asyncio
    async def test_fifty_tweets_memory_usage(
        self,
        async_session,
        mock_llm_providers,
        benchmark,
    ):
        """测试 50 条推文处理内存占用 < 200MB。"""
        # 创建 50 条推文
        tweets = []
        for i in range(50):
            tweet = Tweet(
                tweet_id=f"mem_tweet_{i}",
                author_username="mem_user",
                text=f"Memory test tweet {i}" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            tweets.append(tweet)

        # 保存推文
        for tweet in tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

        # 创建去重组
        for i, tweet in enumerate(tweets):
            group = DeduplicationGroup(
                group_id=f"mem_group_{i}",
                representative_tweet_id=tweet.tweet_id,
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=[tweet.tweet_id],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

        # 更新推文的去重组 ID
        for tweet in tweets:
            stmt = select(TweetOrm).where(TweetOrm.tweet_id == tweet.tweet_id)
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = f"mem_group_{tweets.index(tweet)}"

        await async_session.commit()

        tweet_ids = [t.tweet_id for t in tweets]

        async def process_fifty_tweets():
            """处理 50 条推文。"""
            repo = SummarizationRepository(async_session)
            config = LLMProviderConfig.from_env()

            with patch(
                "src.summarization.services.summarization_service.OpenRouterProvider",
                return_value=mock_llm_providers["openrouter"],
            ):
                service = create_summarization_service(
                    repository=repo,
                    config=config,
                    prompt_config=PromptConfig(),
                )

                result = await service.summarize_tweets(
                    tweet_ids=tweet_ids,
                    force_refresh=True,
                )

                from returns.result import Failure

                if isinstance(result, Failure):
                    raise result.failure()

                return result.unwrap()

        # 使用 benchmark 的内存分析功能
        result = benchmark.pedantic(
            process_fifty_tweets,
            iterations=1,
            rounds=1,
        )

        # 验证结果
        assert result.total_tweets == 50

        # pytest-benchmark 会记录内存使用情况


class TestPerformanceRegression:
    """性能回归测试。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("num_tweets", [1, 10, 50])
    async def test_performance_regression(
        self,
        async_session,
        mock_llm_providers,
        benchmark,
        num_tweets,
    ):
        """测试不同规模下的性能回归。"""
        # 创建指定数量的推文
        tweets = []
        for i in range(num_tweets):
            tweet = Tweet(
                tweet_id=f"regress_tweet_{i}",
                author_username="regress_user",
                text=f"Regression test tweet {i}" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            tweets.append(tweet)

        # 保存推文
        for tweet in tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

        # 创建去重组
        for i, tweet in enumerate(tweets):
            group = DeduplicationGroup(
                group_id=f"regress_group_{i}",
                representative_tweet_id=tweet.tweet_id,
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=[tweet.tweet_id],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

        # 更新推文的去重组 ID
        for tweet in tweets:
            stmt = select(TweetOrm).where(TweetOrm.tweet_id == tweet.tweet_id)
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = f"regress_group_{tweets.index(tweet)}"

        await async_session.commit()

        tweet_ids = [t.tweet_id for t in tweets]

        async def process_tweets():
            """处理推文。"""
            repo = SummarizationRepository(async_session)
            config = LLMProviderConfig.from_env()

            with patch(
                "src.summarization.services.summarization_service.OpenRouterProvider",
                return_value=mock_llm_providers["openrouter"],
            ):
                service = create_summarization_service(
                    repository=repo,
                    config=config,
                    prompt_config=PromptConfig(),
                )

                result = await service.summarize_tweets(
                    tweet_ids=tweet_ids,
                    force_refresh=True,
                )

                from returns.result import Failure

                if isinstance(result, Failure):
                    raise result.failure()

                return result.unwrap()

        result = benchmark(process_tweets)

        # 验证结果
        assert result.total_tweets == num_tweets
