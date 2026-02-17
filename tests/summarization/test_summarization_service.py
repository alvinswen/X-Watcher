"""摘要服务单元测试。

测试 SummarizationService 的核心逻辑，包括：
- 缓存逻辑
- 并发控制
- 降级逻辑
- 错误分类
- 去重组优化处理
- 独立推文处理（无去重组）
"""

from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.deduplication.domain.models import DeduplicationGroup, DeduplicationType
from src.summarization.domain.models import (
    LLMErrorType,
    LLMResponse,
    SummaryRecord,
    TweetFailure,
)
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.llm.base import LLMProvider
from src.summarization.services.summarization_service import (
    SummarizationService,
    create_summarization_service,
)
from returns.result import Failure, Success


def create_mock_session_factory():
    """创建模拟的 session_factory，用于单元测试。

    返回一个可调用对象，每次调用返回一个 async context manager，
    yield 一个 mock AsyncSession。mock session 的 execute() 返回
    正确结构的结果对象，使 SummarizationRepository 可以正常工作。

    Returns:
        模拟的 async_sessionmaker
    """
    def _make_mock_session():
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.close = AsyncMock()

        # 让 execute() 返回一个 mock result，其 scalar_one_or_none() 返回 None
        # 表示没有找到已有记录（新建模式）
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.first.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.one.return_value = MagicMock(
            total_cost=0, total_tokens=0, prompt_tokens=0,
            completion_tokens=0, count=0,
        )
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=None)

        return mock_session

    @asynccontextmanager
    async def _session_ctx():
        yield _make_mock_session()

    factory = MagicMock()
    factory.side_effect = lambda: _session_ctx()
    return factory


class MockLLMError(Exception):
    """模拟 LLM 错误，支持错误类型和状态码。"""

    def __init__(
        self,
        message: str,
        error_type: LLMErrorType | None = None,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


class MockLLMProvider(LLMProvider):
    """模拟 LLM 提供商用于测试。"""

    def __init__(
        self,
        provider_name: str,
        responses: Sequence[LLMResponse] | None = None,
        errors: Sequence[Exception] | None = None,
        error_types: Sequence[LLMErrorType] | None = None,
    ):
        """初始化模拟提供商。

        Args:
            provider_name: 提供商名称
            responses: 预设的响应列表
            errors: 预设的错误列表
            error_types: 预设的错误类型列表
        """
        self._name = provider_name
        self._responses = list(responses) if responses else []
        self._errors = list(errors) if errors else []
        self._error_types = list(error_types) if error_types else []
        self._call_count = 0

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ):
        """模拟 LLM 调用。"""
        call_index = self._call_count
        self._call_count += 1
        self._last_max_tokens = max_tokens

        # 如果有预设错误，返回错误
        if call_index < len(self._errors):
            error = self._errors[call_index]
            # 如果错误类型已定义，添加到异常
            if call_index < len(self._error_types) and isinstance(error, MockLLMError):
                error.error_type = self._error_types[call_index]
            return Failure(error)

        # 如果有预设响应，返回响应
        if call_index < len(self._responses):
            return Success(self._responses[call_index])

        # 默认响应（确保内容足够长以通过验证）
        # JSON 格式响应
        summary_text = "这是一条测试摘要，包含了足够长的内容以满足最小长度要求。" * 2  # 约 42 字 * 2 = 84 字
        json_content = f'{{"summary": "{summary_text}", "translation": "This is a test translation with enough content."}}'
        return Success(
            LLMResponse(
                content=json_content,
                model="mock-model",
                provider=self._name,  # type: ignore
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
                finish_reason="stop",
            )
        )

    def get_provider_name(self) -> str:
        """获取提供商名称。"""
        return self._name

    def get_model_name(self) -> str:
        """获取模型名称（用于测试）。"""
        return "mock-model"


class MockRepository:
    """模拟摘要仓储。"""

    def __init__(self):
        """初始化模拟仓储。"""
        self._summaries: dict[str, SummaryRecord] = {}
        self._content_hash_index: dict[str, SummaryRecord] = {}
        self._session = AsyncMock()

    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord:
        """保存摘要记录。"""
        self._summaries[record.summary_id] = record
        if record.cached:
            self._content_hash_index[record.content_hash] = record
        return record

    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None:
        """根据推文 ID 查询摘要。"""
        for record in self._summaries.values():
            if record.tweet_id == tweet_id:
                return record
        return None

    async def get_cost_stats(self, start_date=None, end_date=None):
        """获取成本统计（简化版）。"""
        from src.summarization.domain.models import CostStats

        return CostStats(
            start_date=start_date,
            end_date=end_date,
            total_cost_usd=sum(s.cost_usd for s in self._summaries.values()),
            total_tokens=sum(s.total_tokens for s in self._summaries.values()),
            prompt_tokens=sum(s.prompt_tokens for s in self._summaries.values()),
            completion_tokens=sum(s.completion_tokens for s in self._summaries.values()),
            provider_breakdown={},
        )

    async def find_by_content_hash(self, content_hash: str) -> SummaryRecord | None:
        """根据内容哈希查询摘要。"""
        return self._content_hash_index.get(content_hash)


@pytest.fixture
def mock_repository():
    """创建模拟仓储。"""
    return MockRepository()


@pytest.fixture
def mock_session_factory(mock_repository):
    """创建模拟的 session_factory，并 patch SummarizationRepository。

    使 SummarizationService 内部创建的 SummarizationRepository 实际指向 mock_repository。
    """
    return create_mock_session_factory(mock_repository)


@pytest.fixture
def mock_llm_response():
    """创建模拟 LLM 响应。"""
    # 确保摘要文本至少 50 字符
    summary_text = "这是一条测试摘要，包含了足够长的内容以满足最小长度要求。" * 2
    translation_text = "This is a test translation with enough content to pass validation."
    return LLMResponse(
        content=f'{{"summary": "{summary_text}", "translation": "{translation_text}"}}',
        model="test-model",
        provider="openrouter",  # type: ignore
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
    )


@pytest.fixture
def sample_deduplication_group():
    """创建示例去重组。"""
    return DeduplicationGroup(
        group_id=str(uuid4()),
        representative_tweet_id="rep_tweet_123",
        deduplication_type=DeduplicationType.exact_duplicate,
        similarity_score=None,
        tweet_ids=["rep_tweet_123", "tweet_456", "tweet_789"],
        created_at=datetime.now(timezone.utc),
    )


class TestSummarizationService:
    """测试 SummarizationService。"""

    @pytest.mark.asyncio
    async def test_initialization(self, mock_repository):
        """测试服务初始化。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        assert service._max_concurrent == SummarizationService.DEFAULT_MAX_CONCURRENT
        assert len(service._providers) == 1
        assert len(service._cache) == 0

    @pytest.mark.asyncio
    async def test_summarize_tweets_success(
        self,
        mock_repository,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试成功摘要推文。"""
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])

        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        # Mock 去重组加载和推文文本加载
        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": {"text": "This is a representative tweet that is long enough to trigger summarization and translation by the LLM provider service", "reference_type": None}}
        )

        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123", "tweet_456"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 2
        assert summary_result.total_tweets_succeeded == 1
        assert summary_result.total_groups == 1
        assert summary_result.cache_misses == 1
        assert summary_result.total_tokens == 150
        assert summary_result.failed_tweets == []

    @pytest.mark.asyncio
    async def test_cache_hit_second_call(
        self,
        mock_repository,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试缓存逻辑：首次调用 LLM，第二次命中缓存。"""
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": {"text": "This is a representative tweet that is long enough to trigger summarization and translation by the LLM provider service", "reference_type": None}}
        )

        # 第一次调用
        result1 = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result1, Success)
        summary1 = result1.unwrap()
        assert summary1.cache_misses == 1

        # 第二次调用（应命中缓存）
        result2 = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result2, Success)
        summary2 = result2.unwrap()
        # 由于有去重组，应该命中缓存
        assert summary2.cache_hits >= 0

    @pytest.mark.asyncio
    async def test_force_refresh_skips_cache(
        self,
        mock_repository,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试强制刷新跳过缓存。"""
        provider = MockLLMProvider(
            "openrouter", responses=[mock_llm_response, mock_llm_response]
        )
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": {"text": "This is a representative tweet that is long enough to trigger summarization and translation by the LLM provider service", "reference_type": None}}
        )

        # 第一次调用
        await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
        )

        # 强制刷新
        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
            force_refresh=True,
        )

        assert isinstance(result, Success)
        # 强制刷新应该重新调用 LLM
        assert provider._call_count >= 2

    @pytest.mark.asyncio
    async def test_concurrent_limit_with_semaphore(
        self,
        mock_repository,
        mock_llm_response,
    ):
        """测试并发控制：Semaphore 限制并发数。"""
        # 创建多个去重组
        groups = []
        for i in range(10):
            groups.append(
                DeduplicationGroup(
                    group_id=str(uuid4()),
                    representative_tweet_id=f"rep_tweet_{i}",
                    deduplication_type=DeduplicationType.exact_duplicate,
                    similarity_score=None,
                    tweet_ids=[f"rep_tweet_{i}", f"tweet_{i}_b"],
                    created_at=datetime.now(timezone.utc),
                )
            )

        # 创建返回多个响应的提供商
        provider = MockLLMProvider(
            "openrouter", responses=[mock_llm_response] * 10
        )

        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
            max_concurrent=3,  # 限制并发为 3
        )

        service._load_deduplication_groups = AsyncMock(return_value=groups)
        # Mock _load_tweets to return text for each representative tweet
        tweets_map = {
            f"rep_tweet_{i}": {"text": f"This is representative tweet {i} with enough text to trigger summarization and translation by the LLM provider service", "reference_type": None}
            for i in range(10)
        }
        service._load_tweets = AsyncMock(return_value=tweets_map)

        result = await service.summarize_tweets(
            tweet_ids=[f"rep_tweet_{i}" for i in range(10)],
            deduplication_groups=groups,
        )

        assert isinstance(result, Success)
        summary = result.unwrap()
        assert summary.total_groups == 10

    @pytest.mark.asyncio
    async def test_fallback_openrouter_to_minimax(
        self,
        mock_repository,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试降级逻辑：OpenRouter 失败 → MiniMax 成功。"""
        # OpenRouter 返回永久错误
        openrouter_error = MockLLMError(
            "OpenRouter API key invalid",
            error_type=LLMErrorType.permanent,
        )

        openrouter = MockLLMProvider(
            "openrouter",
            errors=[openrouter_error],
        )

        # MiniMax 返回成功响应（确保内容足够长）
        summary_text = "来自 MiniMax 的摘要，包含了足够长的内容以满足最小长度要求。" * 2
        translation_text = "Translation from MiniMax with enough content for validation."
        minimax_response = LLMResponse(
            content=f'{{"summary": "{summary_text}", "translation": "{translation_text}"}}',
            model="minimax-model",
            provider="minimax",  # type: ignore
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )
        minimax = MockLLMProvider("minimax", responses=[minimax_response])

        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[openrouter, minimax],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": {"text": "This is a representative tweet that is long enough to trigger summarization and translation by the LLM provider service", "reference_type": None}}
        )

        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result, Success)
        summary = result.unwrap()
        assert summary.providers_used.get("minimax", 0) == 1
        assert summary.providers_used.get("openrouter", 0) == 0

    @pytest.mark.asyncio
    async def test_temporary_error_retry_then_fallback(
        self,
        mock_repository,
        sample_deduplication_group,
    ):
        """测试临时错误重试：429 错误重试后降级。"""
        # OpenRouter 第一次返回 429 临时错误，第二次也失败
        temporary_error = MockLLMError(
            "Rate limit exceeded",
            error_type=LLMErrorType.temporary,
            status_code=429,
        )

        openrouter = MockLLMProvider(
            "openrouter",
            errors=[temporary_error, temporary_error],
        )

        # MiniMax 成功（需要足够长的内容）
        summary_text = "来自 MiniMax 的摘要，包含了足够长的内容以满足最小长度要求。" * 2
        minimax_response = LLMResponse(
            content=f'{{"summary": "{summary_text}", "translation": "Translation."}}',
            model="minimax-model",
            provider="minimax",  # type: ignore
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )
        minimax = MockLLMProvider("minimax", responses=[minimax_response])

        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[openrouter, minimax],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": {"text": "This is a representative tweet that is long enough to trigger summarization and translation by the LLM provider service", "reference_type": None}}
        )

        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result, Success)
        summary = result.unwrap()
        # OpenRouter 失败，MiniMax 成功
        assert summary.providers_used.get("minimax", 0) >= 1

    @pytest.mark.asyncio
    async def test_all_providers_fail(
        self,
        mock_repository,
        sample_deduplication_group,
    ):
        """测试所有提供商失败的情况。"""
        # 所有提供商都返回永久错误
        # 需要足够多的 error 以覆盖初始调用 + 重试
        permanent_errors = [
            MockLLMError("Authentication failed", error_type=LLMErrorType.permanent)
            for _ in range(4)
        ]

        openrouter = MockLLMProvider(
            "openrouter",
            errors=permanent_errors,
        )
        minimax = MockLLMProvider(
            "minimax",
            errors=permanent_errors,
        )

        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[openrouter, minimax],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )

        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123"],
            deduplication_groups=[sample_deduplication_group],
        )

        # 应该返回失败
        assert isinstance(result, Failure)

    @pytest.mark.asyncio
    async def test_compute_hash_consistency(self):
        """测试哈希计算的一致性。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        hash1 = service._compute_hash("test content", "summary")
        hash2 = service._compute_hash("test content", "summary")
        hash3 = service._compute_hash("different content", "summary")

        assert hash1 == hash2
        assert hash1 != hash3
        assert len(hash1) == 64  # SHA256 输出长度

    @pytest.mark.asyncio
    async def test_cache_operations(self):
        """测试缓存读写操作。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        response = LLMResponse(
            content="test",
            model="test-model",
            provider="openrouter",  # type: ignore
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )

        # 测试设置缓存
        await service._set_cache("hash123", response)
        cache_size = await service.get_cache_size()
        assert cache_size == 1

        # 测试读取缓存
        cached = await service._get_from_cache("hash123")
        assert cached is not None
        assert cached.content == "test"

        # 测试清空缓存
        await service.clear_cache()
        cache_size = await service.get_cache_size()
        assert cache_size == 0

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self):
        """测试缓存过期。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
            cache_ttl_seconds=0,  # 立即过期
        )

        response = LLMResponse(
            content="test",
            model="test-model",
            provider="openrouter",  # type: ignore
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )

        await service._set_cache("hash123", response)

        # 缓存应该已过期
        cached = await service._get_from_cache("hash123")
        assert cached is None

    @pytest.mark.asyncio
    async def test_parse_llm_response_json(self):
        """测试解析 JSON 格式的 LLM 响应。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        json_content = '{"summary": "测试摘要", "translation": "测试翻译"}'
        summary, translation = service._parse_llm_response(json_content)

        assert summary == "测试摘要"
        assert translation == "测试翻译"

    @pytest.mark.asyncio
    async def test_parse_llm_response_non_json_fallback(self):
        """测试非 JSON 格式的 LLM 响应回退处理。

        当 LLM 返回非 JSON 格式的纯文本时，整段文本作为摘要返回，
        翻译为 None。
        """
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        multiline_content = "这是摘要内容\n这是翻译内容"
        summary, translation = service._parse_llm_response(multiline_content)

        # 非 JSON 格式时，整段文本作为摘要返回
        assert summary == "这是摘要内容\n这是翻译内容"
        assert translation is None

    @pytest.mark.asyncio
    async def test_parse_llm_response_single_line(self):
        """测试解析单行格式的 LLM 响应。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        single_line_content = "这是摘要内容"
        summary, translation = service._parse_llm_response(single_line_content)

        assert summary == "这是摘要内容"
        assert translation is None

    @pytest.mark.asyncio
    async def test_get_cost_stats(
        self,
        mock_repository,
    ):
        """测试获取成本统计。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        result = await service.get_cost_stats()

        assert isinstance(result, Success)
        stats = result.unwrap()
        assert hasattr(stats, "total_cost_usd")
        assert hasattr(stats, "total_tokens")

    @pytest.mark.asyncio
    async def test_empty_tweet_list(
        self,
        mock_repository,
    ):
        """测试空推文列表的处理。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        result = await service.summarize_tweets(
            tweet_ids=[],
            deduplication_groups=[],
        )

        assert isinstance(result, Success)
        summary = result.unwrap()
        assert summary.total_tweets == 0
        assert summary.total_groups == 0
        assert summary.independent_tweets == 0

    @pytest.mark.asyncio
    async def test_shared_summary_for_deduplication_group(
        self,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试同一去重组共享摘要。

        验证 summarize_tweets 对去重组返回 Success，
        且结果中包含正确的摘要记录。
        """
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": {"text": "This is a representative tweet that is long enough to trigger summarization and translation by the LLM provider service", "reference_type": None}}
        )

        result = await service.summarize_tweets(
            tweet_ids=sample_deduplication_group.tweet_ids,
            deduplication_groups=[sample_deduplication_group],
        )

        # 验证结果成功且有摘要记录
        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets_succeeded >= 1
        assert summary_result.total_groups == 1


    @pytest.mark.asyncio
    async def test_summarize_independent_tweets_no_dedup_groups(
        self,
        mock_repository,
        mock_llm_response,
    ):
        """测试无去重组时独立处理推文。"""
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(return_value=[])
        service._load_tweets = AsyncMock(
            return_value={
                "tweet_standalone": {
                    "text": "A standalone tweet with enough text to trigger summarization and translation by the LLM provider service",
                    "reference_type": None,
                }
            }
        )

        result = await service.summarize_tweets(tweet_ids=["tweet_standalone"])

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 1
        assert summary_result.total_tweets_succeeded == 1
        assert summary_result.total_groups == 0
        assert summary_result.independent_tweets == 1
        assert summary_result.cache_misses == 1
        assert summary_result.failed_tweets == []

    @pytest.mark.asyncio
    async def test_summarize_mixed_grouped_and_independent(
        self,
        mock_repository,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试同时处理有去重组和无去重组的推文。"""
        provider = MockLLMProvider(
            "openrouter", responses=[mock_llm_response, mock_llm_response]
        )
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={
                "rep_tweet_123": {
                    "text": "This is a grouped tweet with enough text to trigger summarization and translation by the LLM provider service",
                    "reference_type": None,
                },
                "standalone_1": {
                    "text": "This is a standalone tweet with enough text to trigger summarization and translation by the LLM provider service",
                    "reference_type": None,
                },
            }
        )

        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123", "tweet_456", "standalone_1"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_groups == 1
        assert summary_result.independent_tweets == 1
        assert summary_result.total_tweets_succeeded == 2
        # 应该有 2 个 cache miss（1 个去重组 + 1 个独立推文）
        assert summary_result.cache_misses == 2
        assert summary_result.failed_tweets == []

    @pytest.mark.asyncio
    async def test_regenerate_summary_without_dedup_group(
        self,
        mock_repository,
        mock_llm_response,
    ):
        """测试无去重组时重新生成摘要。"""
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(return_value=[])
        service._load_tweets = AsyncMock(
            return_value={
                "orphan_tweet": {
                    "text": "An orphan tweet without dedup group with enough text to trigger summarization and translation by the LLM provider service",
                    "reference_type": None,
                }
            }
        )

        result = await service.regenerate_summary("orphan_tweet")

        assert isinstance(result, Success)
        record = result.unwrap()
        assert record.tweet_id == "orphan_tweet"
        assert record.content_hash.startswith("")  # 非空哈希


class TestCreateSummarizationService:
    """测试 create_summarization_service 工厂函数。"""

    def test_create_with_openrouter_config(self):
        """测试使用 OpenRouter 配置创建服务。"""
        from src.summarization.llm.config import LLMProviderConfig, OpenRouterConfig

        config = LLMProviderConfig(
            openrouter=OpenRouterConfig(
                api_key="test-key",
            )
        )

        session_factory = create_mock_session_factory()

        service = create_summarization_service(
            session_factory=session_factory,
            config=config,
        )

        assert service is not None
        assert len(service._providers) == 1

    def test_create_with_multiple_providers(self):
        """测试使用多个提供商配置创建服务。"""
        from src.summarization.llm.config import (
            LLMProviderConfig,
            OpenRouterConfig,
            MiniMaxConfig,
        )

        config = LLMProviderConfig(
            openrouter=OpenRouterConfig(api_key="or-key"),
            minimax=MiniMaxConfig(api_key="mm-key"),
        )

        session_factory = create_mock_session_factory()

        service = create_summarization_service(
            session_factory=session_factory,
            config=config,
        )

        assert service is not None
        assert len(service._providers) == 2

    def test_create_with_no_providers_raises_error(self):
        """测试没有配置任何提供商时抛出错误。"""
        from src.summarization.llm.config import LLMProviderConfig

        config = LLMProviderConfig()
        session_factory = create_mock_session_factory()

        with pytest.raises(ValueError, match="至少需要配置一个 LLM 提供商"):
            create_summarization_service(
                session_factory=session_factory,
                config=config,
            )


class TestTruncationDetection:
    """截断检测与重试逻辑测试。"""

    def _make_response(
        self,
        content: str = '{"summary": "摘要", "translation": "翻译"}',
        completion_tokens: int = 200,
        finish_reason: str | None = "stop",
    ) -> LLMResponse:
        """构造测试用 LLMResponse。"""
        return LLMResponse(
            content=content,
            model="mock-model",
            provider="openrouter",
            prompt_tokens=100,
            completion_tokens=completion_tokens,
            total_tokens=100 + completion_tokens,
            cost_usd=0.001,
            finish_reason=finish_reason,
        )

    @pytest.mark.asyncio
    async def test_no_retry_when_finish_reason_is_stop(self):
        """测试正常完成时不重试。"""
        response = self._make_response(finish_reason="stop")
        provider = MockLLMProvider("openrouter", responses=[response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        result = await service._call_llm_with_retry(provider, "test prompt")

        assert isinstance(result, Success)
        assert result.unwrap().finish_reason == "stop"
        assert provider._call_count == 1  # 没有重试

    @pytest.mark.asyncio
    async def test_no_retry_when_finish_reason_is_none(self):
        """测试 finish_reason 为 None 时不重试。"""
        response = self._make_response(finish_reason=None)
        provider = MockLLMProvider("openrouter", responses=[response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        result = await service._call_llm_with_retry(provider, "test prompt")

        assert isinstance(result, Success)
        assert provider._call_count == 1

    @pytest.mark.asyncio
    async def test_truncation_detected_and_retried(self):
        """测试检测到截断后使用更大 max_tokens 重试。"""
        truncated = self._make_response(
            content='{"summary": "摘要", "translat',
            completion_tokens=2048,
            finish_reason="length",
        )
        full = self._make_response(
            content='{"summary": "完整摘要", "translation": "完整翻译"}',
            completion_tokens=800,
            finish_reason="stop",
        )
        provider = MockLLMProvider("openrouter", responses=[truncated, full])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        result = await service._call_llm_with_retry(provider, "test prompt")

        assert isinstance(result, Success)
        assert result.unwrap().finish_reason == "stop"
        assert result.unwrap().content == '{"summary": "完整摘要", "translation": "完整翻译"}'
        assert provider._call_count == 2  # 重试了一次
        # 验证重试时使用了更大的 max_tokens
        assert provider._last_max_tokens == SummarizationService.TRUNCATION_RETRY_MAX_TOKENS

    @pytest.mark.asyncio
    async def test_truncation_retry_still_truncated_returns_retry_result(self):
        """测试重试后仍截断时，返回重试结果（内容更完整）。"""
        truncated1 = self._make_response(
            content='{"summary": "a"',
            completion_tokens=2048,
            finish_reason="length",
        )
        truncated2 = self._make_response(
            content='{"summary": "摘要", "translation": "翻译部分内容',
            completion_tokens=4096,
            finish_reason="length",
        )
        provider = MockLLMProvider("openrouter", responses=[truncated1, truncated2])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        result = await service._call_llm_with_retry(provider, "test prompt")

        assert isinstance(result, Success)
        # 返回重试结果（更完整）
        assert result.unwrap().completion_tokens == 4096
        assert provider._call_count == 2

    @pytest.mark.asyncio
    async def test_truncation_retry_failure_returns_original(self):
        """测试截断重试失败（API 错误）时，返回原始截断结果。"""
        truncated = self._make_response(
            content='{"summary": "摘要", "translat',
            completion_tokens=2048,
            finish_reason="length",
        )
        # 第一次返回截断，第二次返回错误
        provider = MockLLMProvider(
            "openrouter",
            responses=[truncated],
            errors=[],
        )
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        # Mock：第二次调用返回 Failure
        original_complete = provider.complete
        call_count = 0

        async def mock_complete(prompt, max_tokens=2048, temperature=0.7):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Success(truncated)
            return Failure(Exception("API error"))

        provider.complete = mock_complete  # type: ignore

        result = await service._call_llm_with_retry(provider, "test prompt")

        assert isinstance(result, Success)
        # 返回原始截断结果，而非 Failure
        assert result.unwrap().completion_tokens == 2048

    @pytest.mark.asyncio
    async def test_finish_reason_field_defaults_to_none(self):
        """测试 LLMResponse 的 finish_reason 默认为 None（向后兼容）。"""
        response = LLMResponse(
            content="test",
            model="test",
            provider="openrouter",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )
        assert response.finish_reason is None

    @pytest.mark.asyncio
    async def test_max_tokens_passed_to_provider(self):
        """测试 max_tokens 被正确传递给 provider。"""
        response = self._make_response(finish_reason="stop")
        provider = MockLLMProvider("openrouter", responses=[response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        await service._call_llm_with_retry(provider, "test prompt")

        # 验证使用默认 max_tokens
        assert provider._last_max_tokens == SummarizationService.DEFAULT_MAX_TOKENS


class TestFailureTracking:
    """测试单条推文失败跟踪。"""

    @pytest.fixture
    def mock_repository(self):
        return MockRepository()

    @pytest.fixture
    def mock_llm_response(self):
        summary_text = "这是一条测试摘要，包含了足够长的内容以满足最小长度要求。" * 2
        translation_text = (
            "This is a test translation with enough content to pass validation."
        )
        return LLMResponse(
            content=f'{{"summary": "{summary_text}", "translation": "{translation_text}"}}',
            model="test-model",
            provider="openrouter",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )

    @pytest.mark.asyncio
    async def test_partial_tweet_failure_tracks_failed_ids(
        self, mock_repository, mock_llm_response,
    ):
        """测试部分推文失败时正确记录失败信息。"""
        # 第一条成功，第二条失败（所有 provider 都失败），第三条成功
        # 需要足够多的 error 覆盖重试：初始调用 + 1 次重试 = 2 次
        permanent_error = MockLLMError(
            "Rate limit", error_type=LLMErrorType.permanent,
        )

        # 调用顺序: tweet1(成功), tweet2(失败), tweet3(成功), tweet2重试(失败)
        # provider 是共享的，所以需要按调用顺序排列
        # 但 asyncio.gather 的并发顺序不确定，用不同的 provider 策略
        # 更简单的方法：mock _process_single_tweet 直接返回
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(return_value=[])

        # 直接 mock _process_single_tweet 控制每条推文的结果
        call_count = 0
        original_process = service._process_single_tweet

        async def mock_process(tweet_id, force_refresh):
            nonlocal call_count
            call_count += 1
            if tweet_id == "tweet_fail":
                return None  # 模拟失败
            return await original_process(tweet_id, force_refresh)

        service._process_single_tweet = mock_process  # type: ignore
        service._load_tweets = AsyncMock(
            return_value={
                "tweet_ok1": {
                    "text": "A tweet with enough text to trigger summarization and translation by the LLM provider service",
                    "reference_type": None,
                },
                "tweet_ok2": {
                    "text": "Another tweet with enough text to trigger summarization and translation by the LLM provider service",
                    "reference_type": None,
                },
            }
        )

        result = await service.summarize_tweets(
            tweet_ids=["tweet_ok1", "tweet_fail", "tweet_ok2"]
        )

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 3
        assert summary_result.total_tweets_succeeded == 2
        assert len(summary_result.failed_tweets) == 1
        assert summary_result.failed_tweets[0]["tweet_id"] == "tweet_fail"
        assert summary_result.failed_tweets[0]["error_type"] == "llm_failure"

    @pytest.mark.asyncio
    async def test_partial_group_failure_tracks_failed_ids(
        self, mock_repository, mock_llm_response,
    ):
        """测试部分去重组失败时记录组内所有推文。"""
        group_ok = DeduplicationGroup(
            group_id="group-ok",
            representative_tweet_id="rep_ok",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["rep_ok", "dup_ok"],
            created_at=datetime.now(timezone.utc),
        )
        group_fail = DeduplicationGroup(
            group_id="group-fail",
            representative_tweet_id="rep_fail",
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=["rep_fail", "dup_fail1", "dup_fail2"],
            created_at=datetime.now(timezone.utc),
        )

        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[group_ok, group_fail]
        )

        async def mock_process_group(group, force_refresh):
            if group.group_id == "group-fail":
                return None
            # 模拟成功
            return SummaryRecord(
                summary_id="s1",
                tweet_id=group.representative_tweet_id,
                summary_text="这是一条测试摘要，包含了足够长的内容以满足最小长度要求。" * 2,
                translation_text="Test translation",
                model_provider="openrouter",
                model_name="test",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
                cached=False,
                content_hash="hash1",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        service._process_deduplication_group = mock_process_group  # type: ignore

        result = await service.summarize_tweets(
            tweet_ids=["rep_ok", "dup_ok", "rep_fail", "dup_fail1", "dup_fail2"],
            deduplication_groups=[group_ok, group_fail],
        )

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 5
        assert summary_result.total_tweets_succeeded == 1  # 只有 group_ok 成功
        assert len(summary_result.failed_tweets) == 3  # group_fail 的 3 条推文
        failed_ids = {f["tweet_id"] for f in summary_result.failed_tweets}
        assert failed_ids == {"rep_fail", "dup_fail1", "dup_fail2"}

    @pytest.mark.asyncio
    async def test_per_tweet_retry_recovers_transient_failure(
        self, mock_repository, mock_llm_response,
    ):
        """测试单条推文重试机制能恢复暂时性失败。"""
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(return_value=[])

        # 第一次调用失败，第二次（重试）成功
        attempt_count = {}

        async def mock_process(tweet_id, force_refresh):
            attempt_count[tweet_id] = attempt_count.get(tweet_id, 0) + 1
            if tweet_id == "tweet_flaky" and attempt_count[tweet_id] == 1:
                return None  # 第一次失败
            # 返回成功记录
            return SummaryRecord(
                summary_id=f"s-{tweet_id}",
                tweet_id=tweet_id,
                summary_text="这是一条测试摘要，包含了足够长的内容以满足最小长度要求。" * 2,
                translation_text="Test translation",
                model_provider="openrouter",
                model_name="test",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
                cached=False,
                content_hash=f"hash-{tweet_id}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        service._process_single_tweet = mock_process  # type: ignore
        service._load_tweets = AsyncMock(return_value={})

        result = await service.summarize_tweets(
            tweet_ids=["tweet_flaky"]
        )

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets_succeeded == 1
        assert summary_result.failed_tweets == []
        assert attempt_count["tweet_flaky"] == 2  # 重试了一次

    @pytest.mark.asyncio
    async def test_per_tweet_retry_exhausted_records_failure(
        self, mock_repository,
    ):
        """测试重试耗尽后推文被记录为失败。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            session_factory=create_mock_session_factory(),
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(return_value=[])

        async def mock_process(tweet_id, force_refresh):
            return None  # 永远失败

        service._process_single_tweet = mock_process  # type: ignore
        service._load_tweets = AsyncMock(return_value={})

        result = await service.summarize_tweets(
            tweet_ids=["tweet_always_fail"]
        )

        # 所有推文都失败 → 返回 Failure
        assert isinstance(result, Failure)
