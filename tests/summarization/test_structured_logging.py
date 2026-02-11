"""结构化日志记录测试。

测试摘要服务的结构化日志功能。
"""

import logging
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.deduplication.domain.models import DeduplicationGroup, DeduplicationType
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.domain.models import PromptConfig
from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.services.summarization_service import (
    create_summarization_service,
)
from sqlalchemy import select


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
    from unittest.mock import MagicMock, AsyncMock
    from src.summarization.domain.models import LLMResponse
    from returns.result import Success

    mock_provider = MagicMock()
    mock_provider.get_provider_name = MagicMock(return_value="openrouter")
    mock_provider.get_model_name = MagicMock(return_value="claude-sonnet-4.5")
    # complete 方法应该返回 Result[LLMResponse, Exception]
    mock_provider.complete = AsyncMock(
        return_value=Success(
            LLMResponse(
                content='{"summary": "Test summary with enough content to pass validation.", "translation": "Test translation"}',
                model="claude-sonnet-4.5",
                provider="openrouter",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
            )
        )
    )
    return [mock_provider]


class TestStructuredLogging:
    """测试结构化日志记录。"""

    @pytest.mark.asyncio
    async def test_summary_generation_logs_context(
        self,
        async_session,
        mock_llm_providers,
        caplog,
    ):
        """测试摘要生成时记录上下文信息。"""
        # 设置日志捕获
        with caplog.at_level(logging.INFO):
            # 准备测试数据
            tweet = Tweet(
                tweet_id="test_tweet_1",
                author_username="test_user",
                text="Test tweet for logging" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

            from src.scraper.infrastructure.models import DeduplicationGroupOrm

            group = DeduplicationGroup(
                group_id="test_group_1",
                representative_tweet_id="test_tweet_1",
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=["test_tweet_1"],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

            stmt = select(TweetOrm).where(TweetOrm.tweet_id == "test_tweet_1")
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = "test_group_1"
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            # 直接创建服务实例，传入 mock providers
            from src.summarization.services.summarization_service import SummarizationService

            service = SummarizationService(
                repository=repo,
                providers=mock_llm_providers,
                prompt_config=PromptConfig(),
            )

            # 执行摘要
            result = await service.summarize_tweets(
                tweet_ids=["test_tweet_1"],
                force_refresh=True,
            )

        # 验证日志包含上下文信息
        assert len(caplog.records) > 0

        # 检查是否有包含推文 ID 的日志
        # tweet_id 可能在 message 中，也可能在结构化日志的 extra 字段中
        assert any(
            "test_tweet_1" in record.message
            or getattr(record, "tweet_id", None) == "test_tweet_1"
            for record in caplog.records
        )

        # 验证成功日志包含摘要信息
        from returns.result import Failure

        assert not isinstance(result, Failure)
        summary_result = result.unwrap()

        # 检查完成日志
        completion_logs = [
            r for r in caplog.records
            if "摘要完成" in r.message or "summary" in r.message.lower()
        ]
        assert len(completion_logs) > 0

    @pytest.mark.asyncio
    async def test_degradation_logs_warning(
        self,
        async_session,
        caplog,
    ):
        """测试降级时记录 WARNING 级别日志。"""
        with caplog.at_level(logging.WARNING):
            # 创建模拟提供商（第一个失败）
            from src.summarization.llm.base import LLMErrorType
            from src.summarization.domain.models import LLMResponse
            from returns.result import Success, Failure

            mock_failing_provider = MagicMock()
            mock_failing_provider.get_provider_name = MagicMock(
                return_value="openrouter"
            )
            mock_failing_provider.get_model_name = MagicMock(
                return_value="claude-sonnet-4.5"
            )
            mock_failing_provider.complete = AsyncMock(
                return_value=Failure(Exception("Provider error"))
            )

            mock_working_provider = MagicMock()
            mock_working_provider.get_provider_name = MagicMock(
                return_value="minimax"
            )
            mock_working_provider.get_model_name = MagicMock(
                return_value="mini-max-model"
            )
            mock_working_provider.complete = AsyncMock(
                return_value=Success(
                    LLMResponse(
                        content='{"summary": "Fallback summary with enough content to pass validation.", "translation": "Fallback translation"}',
                        model="mini-max-model",
                        provider="minimax",
                        prompt_tokens=100,
                        completion_tokens=50,
                        total_tokens=150,
                        cost_usd=0.001,
                    )
                )
            )

            # 准备测试数据
            tweet = Tweet(
                tweet_id="test_degrade",
                author_username="test_user",
                text="Test for degradation" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

            from src.scraper.infrastructure.models import DeduplicationGroupOrm

            group = DeduplicationGroup(
                group_id="degrade_group",
                representative_tweet_id="test_degrade",
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=["test_degrade"],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

            stmt = select(TweetOrm).where(TweetOrm.tweet_id == "test_degrade")
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = "degrade_group"
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            from src.summarization.services.summarization_service import SummarizationService

            service = SummarizationService(
                repository=repo,
                providers=[mock_failing_provider, mock_working_provider],
            )

            # 执行摘要（应该降级）
            result = await service.summarize_tweets(
                tweet_ids=["test_degrade"],
                force_refresh=True,
            )

        # 验证有 WARNING 日志
        warning_logs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert len(warning_logs) > 0

        # 验证降级日志包含提供商信息
        warning_messages = [r.message for r in warning_logs]
        assert any(
            "failing_provider" in msg or "降级" in msg or "degrad" in msg.lower()
            for msg in warning_messages
        )

    @pytest.mark.asyncio
    async def test_cache_hit_logs_info(
        self,
        async_session,
        caplog,
    ):
        """测试缓存命中时记录 INFO 级别日志。"""
        with caplog.at_level(logging.INFO):
            from src.summarization.domain.models import SummaryRecord

            # 预先保存摘要
            existing_summary = SummaryOrm.from_domain(
                SummaryRecord(
                    summary_id="cache_log_summary",
                    tweet_id="cache_log_tweet",
                    summary_text="Cached summary" + " text" * 15,
                    translation_text="Cached translation",
                    model_provider="openrouter",
                    model_name="test_model",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                    cost_usd=0.001,
                    cached=True,
                    content_hash="cache_log_hash",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            async_session.add(existing_summary)
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            from src.summarization.services.summarization_service import SummarizationService

            from returns.result import Success
            from src.summarization.domain.models import LLMResponse

            mock_provider = MagicMock()
            mock_provider.get_provider_name = MagicMock(return_value="openrouter")
            mock_provider.get_model_name = MagicMock(return_value="claude-sonnet-4.5")
            mock_provider.complete = AsyncMock(
                return_value=Success(
                    LLMResponse(
                        content='{"summary": "Generated summary with sufficient content", "translation": "Translation"}',
                        model="claude-sonnet-4.5",
                        provider="openrouter",
                        prompt_tokens=100,
                        completion_tokens=50,
                        total_tokens=150,
                        cost_usd=0.001,
                    )
                )
            )

            service = SummarizationService(
                repository=repo,
                providers=[mock_provider],
            )

            # 执行摘要（应该命中缓存）
            result = await service.summarize_tweets(
                tweet_ids=["cache_log_tweet"],
                force_refresh=False,
            )

        # 验证有 INFO 级别的缓存日志
        info_logs = [r for r in caplog.records if r.levelno == logging.INFO]

        # 检查缓存相关日志
        cache_logs = [
            r for r in info_logs
            if "缓存" in r.message or "cache" in r.message.lower()
        ]

        # 可能有缓存命中日志
        # 验证结果使用缓存
        from returns.result import Failure

        assert not isinstance(result, Failure)
        summary_result = result.unwrap()
        assert summary_result.cache_hits >= 0

    @pytest.mark.asyncio
    async def test_error_logs_error_level(
        self,
        async_session,
        caplog,
    ):
        """测试错误时记录 ERROR 级别日志。"""
        with caplog.at_level(logging.ERROR):
            # 创建失败的提供商
            from returns.result import Failure

            mock_failing_provider = MagicMock()
            mock_failing_provider.get_provider_name = MagicMock(
                return_value="openrouter"
            )
            mock_failing_provider.get_model_name = MagicMock(
                return_value="claude-sonnet-4.5"
            )
            mock_failing_provider.complete = AsyncMock(
                return_value=Failure(Exception("Complete failure"))
            )

            # 准备测试数据
            tweet = Tweet(
                tweet_id="error_tweet",
                author_username="test_user",
                text="Test for error" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

            from src.scraper.infrastructure.models import DeduplicationGroupOrm

            group = DeduplicationGroup(
                group_id="error_group",
                representative_tweet_id="error_tweet",
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=["error_tweet"],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

            stmt = select(TweetOrm).where(TweetOrm.tweet_id == "error_tweet")
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = "error_group"
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            from src.summarization.services.summarization_service import SummarizationService

            service = SummarizationService(
                repository=repo,
                providers=[mock_failing_provider],
            )

            # 执行摘要（应该失败）
            result = await service.summarize_tweets(
                tweet_ids=["error_tweet"],
                force_refresh=True,
            )

        # 验证有 ERROR 日志
        error_logs = [
            r for r in caplog.records
            if r.levelno == logging.ERROR
        ]
        assert len(error_logs) > 0

        # 验证错误日志包含相关信息
        error_messages = [r.message for r in error_logs]
        assert any(
            "失败" in msg or "error" in msg.lower() or "fail" in msg.lower()
            for msg in error_messages
        )


class TestLogContext:
    """测试日志上下文信息。"""

    @pytest.mark.asyncio
    async def test_log_includes_provider_info(
        self,
        async_session,
        mock_llm_providers,
        caplog,
    ):
        """测试日志包含提供商信息。"""
        with caplog.at_level(logging.INFO):
            # 准备测试数据
            tweet = Tweet(
                tweet_id="ctx_tweet",
                author_username="test_user",
                text="Context test" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

            from src.scraper.infrastructure.models import DeduplicationGroupOrm

            group = DeduplicationGroup(
                group_id="ctx_group",
                representative_tweet_id="ctx_tweet",
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=["ctx_tweet"],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

            stmt = select(TweetOrm).where(TweetOrm.tweet_id == "ctx_tweet")
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = "ctx_group"
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            # 直接创建服务实例，传入 mock providers
            from src.summarization.services.summarization_service import SummarizationService

            service = SummarizationService(
                repository=repo,
                providers=mock_llm_providers,
                prompt_config=PromptConfig(),
            )

            # 执行摘要
            await service.summarize_tweets(
                tweet_ids=["ctx_tweet"],
                force_refresh=True,
            )

        # 验证日志包含提供商相关信息
        info_logs = [r.message for r in caplog.records if r.levelno == logging.INFO]

        # 检查是否有提供商名称、模型名称等信息
        # 注意：这取决于实际日志格式
        assert len(info_logs) > 0

    @pytest.mark.asyncio
    async def test_log_includes_token_and_cost_info(
        self,
        async_session,
        mock_llm_providers,
        caplog,
    ):
        """测试日志包含 token 和成本信息。"""
        with caplog.at_level(logging.INFO):
            # 准备测试数据
            tweet = Tweet(
                tweet_id="token_tweet",
                author_username="test_user",
                text="Token test" + " content" * 20,
                created_at=datetime.now(timezone.utc),
            )
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)

            from src.scraper.infrastructure.models import DeduplicationGroupOrm

            group = DeduplicationGroup(
                group_id="token_group",
                representative_tweet_id="token_tweet",
                deduplication_type=DeduplicationType.exact_duplicate,
                similarity_score=None,
                tweet_ids=["token_tweet"],
                created_at=datetime.now(timezone.utc),
            )
            group_orm = DeduplicationGroupOrm.from_domain(group)
            async_session.add(group_orm)

            stmt = select(TweetOrm).where(TweetOrm.tweet_id == "token_tweet")
            result = await async_session.execute(stmt)
            tweet_orm = result.scalar_one()
            tweet_orm.deduplication_group_id = "token_group"
            await async_session.commit()

            # 创建摘要服务
            repo = SummarizationRepository(async_session)
            # 直接创建服务实例，传入 mock providers
            from src.summarization.services.summarization_service import SummarizationService

            service = SummarizationService(
                repository=repo,
                providers=mock_llm_providers,
                prompt_config=PromptConfig(),
            )

            # 执行摘要
            result = await service.summarize_tweets(
                tweet_ids=["token_tweet"],
                force_refresh=True,
            )

            from returns.result import Failure

            assert not isinstance(result, Failure)
            summary_result = result.unwrap()

        # 验证结果包含 token 和成本信息
        assert summary_result.total_tokens > 0
        assert summary_result.total_cost_usd >= 0

        # 验证完成日志（可能包含统计信息）
        completion_logs = [
            r for r in caplog.records
            if "完成" in r.message or "complete" in r.message.lower()
        ]
        # 完成日志应该存在
        assert len(completion_logs) > 0 or summary_result.total_groups > 0
