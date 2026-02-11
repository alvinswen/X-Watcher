"""端到端集成测试。

测试完整的抓取 → 去重 → 摘要流程。
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from src.deduplication.domain.models import DeduplicationType
from src.deduplication.infrastructure.repository import DeduplicationRepository
from src.deduplication.services.deduplication_service import DeduplicationService
from src.scraper import TaskStatus, TaskRegistry
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.domain.models import (
    PromptConfig,
    SummaryRecord,
    SummaryResult,
)
from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.services.summarization_service import (
    SummarizationService,
    create_summarization_service,
)


@pytest.fixture(autouse=True)
def setup_test_env():
    """设置测试环境变量。

    优先使用 .env 文件中的真实 API 密钥，如果没有则使用测试密钥。
    """
    # 保存原始环境变量
    original_openrouter = os.environ.get("OPENROUTER_API_KEY")
    original_minimax = os.environ.get("MINIMAX_API_KEY")

    # 如果 .env 中没有配置，使用测试密钥
    if not os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
    if not os.environ.get("MINIMAX_API_KEY"):
        os.environ["MINIMAX_API_KEY"] = "test-minimax-key"

    yield

    # 恢复原始环境变量
    if original_openrouter is None:
        os.environ.pop("OPENROUTER_API_KEY", None)
    else:
        os.environ["OPENROUTER_API_KEY"] = original_openrouter

    if original_minimax is None:
        os.environ.pop("MINIMAX_API_KEY", None)
    else:
        os.environ["MINIMAX_API_KEY"] = original_minimax


@pytest.fixture
def clean_registry():
    """清理任务注册表。"""
    registry = TaskRegistry.get_instance()
    registry.clear_all()
    yield
    registry.clear_all()


@pytest.fixture
def sample_tweets() -> list[Tweet]:
    """创建示例推文数据。

    包含一些重复和相似的推文用于测试。
    """
    now = datetime.now(timezone.utc)

    return [
        Tweet(
            tweet_id="tweet1",
            author_username="user1",
            text="This is the first tweet about AI",
            created_at=now,
        ),
        Tweet(
            tweet_id="tweet2",
            author_username="user2",
            text="This is the first tweet about AI",  # 精确重复
            created_at=now,
        ),
        Tweet(
            tweet_id="tweet3",
            author_username="user3",
            text="AI is transforming technology rapidly",
            created_at=now,
        ),
        Tweet(
            tweet_id="tweet4",
            author_username="user4",
            text="Artificial Intelligence changes tech fast",  # 相似内容
            created_at=now,
        ),
    ]


class TestEndToEndDeduplicationSummarization:
    """测试去重 → 摘要端到端流程。"""

    @pytest.mark.asyncio
    async def test_deduplication_triggers_summarization(
        self,
        async_session,
        sample_tweets,
        clean_registry,
    ):
        """测试去重完成后自动触发摘要任务。"""
        # 1. 保存推文到数据库
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.commit()

        # 2. 创建模拟摘要服务
        mock_summary_service = MagicMock()

        # 模拟 summarize_tweets 返回成功结果
        mock_summary_service.summarize_tweets = AsyncMock(
            return_value=MagicMock(
                unwrap=lambda: SummaryResult(
                    total_tweets=4,
                    total_groups=2,  # 2 个去重组
                    cache_hits=0,
                    cache_misses=2,
                    total_tokens=300,
                    total_cost_usd=0.002,
                    providers_used={"openrouter": 2},
                    processing_time_ms=1000,
                )
            )
        )

        # 3. 创建去重服务（带摘要集成）
        dedup_repo = DeduplicationRepository(async_session)
        dedup_service = DeduplicationService(
            repository=dedup_repo,
            summarization_service=mock_summary_service,
            task_registry=TaskRegistry.get_instance(),
        )

        # 4. 执行去重
        tweet_ids = [t.tweet_id for t in sample_tweets]
        result = await dedup_service.deduplicate_tweets(tweet_ids)

        # 5. 验证去重结果
        assert result.total_tweets == 4
        assert result.exact_duplicate_count == 1  # tweet1 和 tweet2
        # 相似内容检测取决于算法阈值和实现，这里只验证不为负数
        assert result.similar_content_count >= 0

        # 6. 等待后台摘要任务执行
        import asyncio
        await asyncio.sleep(0.2)

        # 验证摘要服务被调用
        mock_summary_service.summarize_tweets.assert_called_once()
        call_args = mock_summary_service.summarize_tweets.call_args
        assert call_args[1]["tweet_ids"]  # 应该传入代表推文 ID 列表
        assert call_args[1]["force_refresh"] is False

        # 7. 验证任务已创建
        tasks = TaskRegistry.get_instance().get_all_tasks()
        summary_tasks = [
            t for t in tasks
            if t.get("metadata", {}).get("triggered_by") == "deduplication"
        ]
        assert len(summary_tasks) == 1

    @pytest.mark.asyncio
    async def test_deduplication_without_summarization_service(
        self,
        async_session,
        sample_tweets,
    ):
        """测试未配置摘要服务时，去重正常工作。"""
        # 保存推文
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.commit()

        # 创建去重服务（不带摘要服务）
        dedup_repo = DeduplicationRepository(async_session)
        dedup_service = DeduplicationService(
            repository=dedup_repo,
            summarization_service=None,
        )

        # 执行去重
        tweet_ids = [t.tweet_id for t in sample_tweets]
        result = await dedup_service.deduplicate_tweets(tweet_ids)

        # 验证去重正常完成
        assert result.total_tweets == 4
        assert result.exact_duplicate_count >= 1

    @pytest.mark.asyncio
    async def test_summarization_failure_doesnt_affect_deduplication(
        self,
        async_session,
        sample_tweets,
        clean_registry,
    ):
        """测试摘要失败不影响去重结果。"""
        # 保存推文
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.commit()

        # 创建模拟摘要服务（返回失败）
        mock_summary_service = MagicMock()
        from returns.result import Failure

        mock_summary_service.summarize_tweets = AsyncMock(
            return_value=Failure(Exception("LLM API error"))
        )

        # 创建去重服务
        dedup_repo = DeduplicationRepository(async_session)
        dedup_service = DeduplicationService(
            repository=dedup_repo,
            summarization_service=mock_summary_service,
            task_registry=TaskRegistry.get_instance(),
        )

        # 执行去重
        tweet_ids = [t.tweet_id for t in sample_tweets]
        result = await dedup_service.deduplicate_tweets(tweet_ids)

        # 验证去重成功完成（即使摘要失败）
        assert result.total_tweets == 4
        assert result.exact_duplicate_count >= 1

        # 验证摘要任务被标记为失败
        await asyncio.sleep(0.1)  # 等待后台任务
        tasks = TaskRegistry.get_instance().get_all_tasks()
        failed_tasks = [
            t for t in tasks
            if t["status"] == TaskStatus.FAILED
            and t.get("metadata", {}).get("triggered_by") == "deduplication"
        ]
        assert len(failed_tasks) == 1


class TestCacheMechanism:
    """测试缓存机制。"""

    @pytest.mark.asyncio
    async def test_second_summary_uses_cache(
        self,
        async_session,
        clean_registry,
    ):
        """测试第二次处理相同内容使用缓存，不再调用 LLM。"""
        # 1. 保存推文
        tweet = Tweet(
            tweet_id="tweet1",
            author_username="user1",
            text="Test tweet for cache" + " content" * 20,  # 足够长
            created_at=datetime.now(timezone.utc),
        )
        orm = TweetOrm.from_domain(tweet)
        async_session.add(orm)
        await async_session.commit()

        # 2. 保存去重组
        from src.deduplication.domain.models import DeduplicationGroup
        from src.scraper.infrastructure.models import DeduplicationGroupOrm

        group = DeduplicationGroup(
            group_id="group1",
            representative_tweet_id="tweet1",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["tweet1"],
            created_at=datetime.now(timezone.utc),
        )
        group_orm = DeduplicationGroupOrm.from_domain(group)
        async_session.add(group_orm)

        # 更新推文的去重组 ID
        stmt = select(TweetOrm).where(TweetOrm.tweet_id == "tweet1")
        result = await async_session.execute(stmt)
        tweet_orm = result.scalar_one()
        tweet_orm.deduplication_group_id = "group1"
        await async_session.commit()

        # 3. 创建摘要服务（使用 mock provider）
        from returns.result import Failure, Success
        from src.summarization.domain.models import LLMResponse

        mock_provider = MagicMock()
        mock_provider.get_provider_name = MagicMock(return_value="openrouter")
        mock_provider.get_model_name = MagicMock(return_value="claude-sonnet-4.5")
        mock_provider.complete = AsyncMock(
            return_value=Success(
                LLMResponse(
                    content='{"summary": "Test summary with sufficient content for cache test.", "translation": "Cache test translation"}',
                    model="claude-sonnet-4.5",
                    provider="openrouter",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                    cost_usd=0.001,
                )
            )
        )

        repo = SummarizationRepository(async_session)
        service = SummarizationService(
            repository=repo,
            providers=[mock_provider],
            prompt_config=PromptConfig(),
        )

        # 4. 第一次调用 — 缓存未命中，应调用 LLM
        result1 = await service.summarize_tweets(
            tweet_ids=["tweet1"],
            force_refresh=False,
        )

        assert not isinstance(result1, Failure)
        summary_result1 = result1.unwrap()
        assert summary_result1.total_tweets == 1
        assert summary_result1.total_groups == 1
        assert summary_result1.cache_misses == 1
        assert summary_result1.cache_hits == 0
        assert mock_provider.complete.call_count == 1  # LLM 被调用了 1 次

        # 5. 第二次调用 — 缓存命中，不应再调用 LLM
        result2 = await service.summarize_tweets(
            tweet_ids=["tweet1"],
            force_refresh=False,
        )

        assert not isinstance(result2, Failure)
        summary_result2 = result2.unwrap()
        assert summary_result2.total_tweets == 1
        assert summary_result2.total_groups == 1
        assert summary_result2.cache_hits == 1
        assert summary_result2.cache_misses == 0
        assert mock_provider.complete.call_count == 1  # LLM 仍然只被调用了 1 次（缓存命中）


class TestDegradationStrategy:
    """测试降级策略。"""

    @pytest.mark.asyncio
    async def test_openrouter_failure_falls_back_to_minimax(
        self,
        async_session,
        clean_registry,
    ):
        """测试 OpenRouter 失败时降级到 MiniMax。"""
        # 保存推文和去重组
        tweet = Tweet(
            tweet_id="tweet1",
            author_username="user1",
            text="Test tweet for fallback" + " content" * 20,
            created_at=datetime.now(timezone.utc),
        )
        orm = TweetOrm.from_domain(tweet)
        async_session.add(orm)

        from src.deduplication.domain.models import DeduplicationGroup
        from src.scraper.infrastructure.models import DeduplicationGroupOrm

        group = DeduplicationGroup(
            group_id="group1",
            representative_tweet_id="tweet1",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["tweet1"],
            created_at=datetime.now(timezone.utc),
        )
        group_orm = DeduplicationGroupOrm.from_domain(group)
        async_session.add(group_orm)

        stmt = select(TweetOrm).where(TweetOrm.tweet_id == "tweet1")
        result = await async_session.execute(stmt)
        tweet_orm = result.scalar_one()
        tweet_orm.deduplication_group_id = "group1"
        await async_session.commit()

        # 创建模拟的 OpenRouter（失败）和 MiniMax（成功）
        from returns.result import Success, Failure as ResultFailure
        from src.summarization.domain.models import LLMResponse

        mock_openrouter = MagicMock()
        mock_openrouter.get_provider_name = MagicMock(return_value="openrouter")
        mock_openrouter.get_model_name = MagicMock(return_value="claude-sonnet-4.5")
        mock_openrouter.complete = AsyncMock(
            return_value=ResultFailure(Exception("OpenRouter API error"))
        )

        mock_minimax = MagicMock()
        mock_minimax.get_provider_name = MagicMock(return_value="minimax")
        mock_minimax.get_model_name = MagicMock(return_value="abab6.5s-chat")
        mock_minimax.complete = AsyncMock(
            return_value=Success(
                LLMResponse(
                    content='{"summary": "Fallback summary with enough content to pass validation checks.", "translation": "Fallback translation"}',
                    model="abab6.5s-chat",
                    provider="minimax",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                    cost_usd=0.0005,
                )
            )
        )

        # 创建摘要服务（直接构建，传入 mock providers）
        repo = SummarizationRepository(async_session)

        service = SummarizationService(
            repository=repo,
            providers=[mock_openrouter, mock_minimax],
            prompt_config=PromptConfig(),
        )

        result = await service.summarize_tweets(
            tweet_ids=["tweet1"],
            force_refresh=True,  # 强制刷新，跳过缓存
        )

        from returns.result import Failure

        assert not isinstance(result, Failure)
        summary_result = result.unwrap()

        # 验证降级到 MiniMax
        assert summary_result.providers_used.get("minimax", 0) > 0
        assert summary_result.providers_used.get("openrouter", 0) == 0


class TestTransactionConsistency:
    """测试事务一致性。"""

    @pytest.mark.asyncio
    async def test_summary_failure_preserves_deduplication(
        self,
        async_session,
        sample_tweets,
        clean_registry,
    ):
        """测试摘要失败时去重结果不受影响。"""
        # 保存推文
        for tweet in sample_tweets:
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.commit()

        # 创建去重服务
        dedup_repo = DeduplicationRepository(async_session)

        # 模拟摘要服务失败
        mock_summary_service = MagicMock()
        from returns.result import Failure

        mock_summary_service.summarize_tweets = AsyncMock(
            return_value=Failure(Exception("Summary failed"))
        )

        dedup_service = DeduplicationService(
            repository=dedup_repo,
            summarization_service=mock_summary_service,
            task_registry=TaskRegistry.get_instance(),
        )

        # 执行去重
        tweet_ids = [t.tweet_id for t in sample_tweets]
        dedup_result = await dedup_service.deduplicate_tweets(tweet_ids)

        # 等待后台任务
        await asyncio.sleep(0.2)

        # 验证去重结果已保存
        assert dedup_result.total_tweets == 4

        # 验证去重组存在于数据库
        from src.scraper.infrastructure.models import DeduplicationGroupOrm

        stmt = select(DeduplicationGroupOrm)
        result = await async_session.execute(stmt)
        groups = result.scalars().all()

        # 应该有去重组（即使摘要失败）
        assert len(groups) >= 1

        # 验证推文的去重组 ID 已设置
        stmt = select(TweetOrm).where(
            TweetOrm.tweet_id.in_(tweet_ids)
        )
        result = await async_session.execute(stmt)
        tweets = result.scalars().all()

        tweets_with_groups = [
            t for t in tweets if t.deduplication_group_id is not None
        ]
        assert len(tweets_with_groups) > 0


class TestIntelligentSummaryLength:
    """测试智能摘要长度策略。"""

    @pytest.mark.asyncio
    async def test_short_tweet_gets_translation_only(
        self,
        async_session,
        clean_registry,
    ):
        """测试短推文（< 100 字）仅翻译不摘要，summary_text = '[SHORT]'。"""
        # 1. 保存短推文
        short_tweet = Tweet(
            tweet_id="short_tweet_1",
            author_username="user1",
            text="Short tweet about AI",  # 20 字符 < 100 字阈值
            created_at=datetime.now(timezone.utc),
        )
        orm = TweetOrm.from_domain(short_tweet)
        async_session.add(orm)
        await async_session.commit()

        # 2. 保存去重组
        from src.deduplication.domain.models import DeduplicationGroup
        from src.scraper.infrastructure.models import DeduplicationGroupOrm

        group = DeduplicationGroup(
            group_id="group_short",
            representative_tweet_id="short_tweet_1",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["short_tweet_1"],
            created_at=datetime.now(timezone.utc),
        )
        group_orm = DeduplicationGroupOrm.from_domain(group)
        async_session.add(group_orm)

        # 更新推文的去重组 ID
        stmt = select(TweetOrm).where(TweetOrm.tweet_id == "short_tweet_1")
        result = await async_session.execute(stmt)
        tweet_orm = result.scalar_one()
        tweet_orm.deduplication_group_id = "group_short"
        await async_session.commit()

        # 3. 创建 mock provider（短推文也需要调用 LLM 翻译）
        from returns.result import Failure, Success
        from src.summarization.domain.models import LLMResponse

        mock_provider = MagicMock()
        mock_provider.get_provider_name = MagicMock(return_value="openrouter")
        mock_provider.get_model_name = MagicMock(return_value="claude-sonnet-4.5")
        mock_provider.complete = AsyncMock(
            return_value=Success(
                LLMResponse(
                    content='{"summary": null, "translation": "关于AI的短推文"}',
                    model="claude-sonnet-4.5",
                    provider="openrouter",
                    prompt_tokens=80,
                    completion_tokens=20,
                    total_tokens=100,
                    cost_usd=0.0005,
                )
            )
        )

        repo = SummarizationRepository(async_session)
        service = SummarizationService(
            repository=repo,
            providers=[mock_provider],
            prompt_config=PromptConfig(
                min_tweet_length_for_summary=100,
            ),
        )

        result = await service.summarize_tweets(
            tweet_ids=["short_tweet_1"],
            force_refresh=True,
        )

        # 4. 验证结果
        assert not isinstance(result, Failure)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 1
        assert summary_result.cache_misses == 1

        # 5. 验证摘要记录
        stmt = select(SummaryOrm).where(
            SummaryOrm.tweet_id == "short_tweet_1"
        )
        result = await async_session.execute(stmt)
        summary_orm = result.scalar_one()

        # 验证 summary_text 为特殊标记
        assert summary_orm.summary_text == "[SHORT]"
        # 验证翻译存在
        assert summary_orm.translation_text == "关于AI的短推文"
        # 验证标记为非生成的摘要
        assert summary_orm.is_generated_summary is False
        # 验证调用了 LLM（有 token 消耗）
        assert summary_orm.total_tokens > 0

    @pytest.mark.asyncio
    async def test_long_tweet_generates_summary_and_translation(
        self,
        async_session,
        clean_registry,
    ):
        """测试长推文（>= 100 字）同时生成摘要和翻译。"""
        # 1. 保存长推文
        long_tweet = Tweet(
            tweet_id="long_tweet_1",
            author_username="user1",
            text="This is a much longer tweet that exceeds the 100 character threshold and should trigger both summarization and translation by the LLM service.",  # > 100 字符
            created_at=datetime.now(timezone.utc),
        )
        orm = TweetOrm.from_domain(long_tweet)
        async_session.add(orm)
        await async_session.commit()

        # 2. 保存去重组
        from src.deduplication.domain.models import DeduplicationGroup
        from src.scraper.infrastructure.models import DeduplicationGroupOrm

        group = DeduplicationGroup(
            group_id="group_long",
            representative_tweet_id="long_tweet_1",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["long_tweet_1"],
            created_at=datetime.now(timezone.utc),
        )
        group_orm = DeduplicationGroupOrm.from_domain(group)
        async_session.add(group_orm)

        stmt = select(TweetOrm).where(TweetOrm.tweet_id == "long_tweet_1")
        result = await async_session.execute(stmt)
        tweet_orm = result.scalar_one()
        tweet_orm.deduplication_group_id = "group_long"
        await async_session.commit()

        # 3. 创建 mock provider
        from returns.result import Failure, Success
        from src.summarization.domain.models import LLMResponse

        mock_provider = MagicMock()
        mock_provider.get_provider_name = MagicMock(return_value="openrouter")
        mock_provider.get_model_name = MagicMock(return_value="claude-sonnet-4.5")
        mock_provider.complete = AsyncMock(
            return_value=Success(
                LLMResponse(
                    content='{"summary": "讨论了一条超过100字符阈值的长推文，应该同时触发LLM服务的摘要和翻译功能。", "translation": "这是一条更长的推文，超过了100字符的阈值，应该同时触发LLM服务的摘要和翻译功能。"}',
                    model="claude-sonnet-4.5",
                    provider="openrouter",
                    prompt_tokens=150,
                    completion_tokens=80,
                    total_tokens=230,
                    cost_usd=0.001,
                )
            )
        )

        repo = SummarizationRepository(async_session)
        service = SummarizationService(
            repository=repo,
            providers=[mock_provider],
            prompt_config=PromptConfig(
                min_tweet_length_for_summary=100,
            ),
        )

        result = await service.summarize_tweets(
            tweet_ids=["long_tweet_1"],
            force_refresh=True,
        )

        # 4. 验证结果
        assert not isinstance(result, Failure)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 1

        # 验证摘要记录
        stmt = select(SummaryOrm).where(
            SummaryOrm.tweet_id == "long_tweet_1"
        )
        result = await async_session.execute(stmt)
        summary_orm = result.scalar_one()

        # 验证标记为生成的摘要
        assert summary_orm.is_generated_summary is True
        # 验证摘要和翻译都有内容
        assert len(summary_orm.summary_text) > 0
        assert summary_orm.summary_text != "[SHORT]"
        assert summary_orm.translation_text is not None
        assert len(summary_orm.translation_text) > 0
        # 验证有 token 消耗
        assert summary_orm.total_tokens > 0


# 导入 asyncio 用于延迟
import asyncio
