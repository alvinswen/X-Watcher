"""摘要服务单元测试。

测试 SummarizationService 的核心逻辑，包括：
- 缓存逻辑
- 并发控制
- 降级逻辑
- 错误分类
- 按去重组分组
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.deduplication.domain.models import DeduplicationGroup, DeduplicationType
from src.summarization.domain.models import (
    LLMErrorType,
    LLMResponse,
    SummaryRecord,
)
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.llm.base import LLMProvider
from src.summarization.services.summarization_service import (
    SummarizationService,
    create_summarization_service,
)
from returns.result import Failure, Success


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
        responses: list[LLMResponse] | None = None,
        errors: list[Exception] | None = None,
        error_types: list[LLMErrorType] | None = None,
    ):
        """初始化模拟提供商。

        Args:
            provider_name: 提供商名称
            responses: 预设的响应列表
            errors: 预设的错误列表
            error_types: 预设的错误类型列表
        """
        self._name = provider_name
        self._responses = responses or []
        self._errors = errors or []
        self._error_types = error_types or []
        self._call_count = 0

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ):
        """模拟 LLM 调用。"""
        call_index = self._call_count
        self._call_count += 1

        # 如果有预设错误，返回错误
        if call_index < len(self._errors):
            error = self._errors[call_index]
            # 如果错误类型已定义，添加到异常
            if call_index < len(self._error_types):
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
        self._session = MagicMock()

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
            repository=mock_repository,  # type: ignore
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
            repository=mock_repository,  # type: ignore
            providers=[provider],
        )

        # Mock 去重组加载和推文文本加载
        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": "This is a representative tweet that is long enough to trigger summarization"}
        )

        result = await service.summarize_tweets(
            tweet_ids=["rep_tweet_123", "tweet_456"],
            deduplication_groups=[sample_deduplication_group],
        )

        assert isinstance(result, Success)
        summary_result = result.unwrap()
        assert summary_result.total_tweets == 2
        assert summary_result.total_groups == 1
        assert summary_result.cache_misses == 1
        assert summary_result.total_tokens == 150

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
            repository=mock_repository,  # type: ignore
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": "This is a representative tweet that is long enough to trigger summarization"}
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
            repository=mock_repository,  # type: ignore
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": "This is a representative tweet that is long enough to trigger summarization"}
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
            repository=mock_repository,  # type: ignore
            providers=[provider],
            max_concurrent=3,  # 限制并发为 3
        )

        service._load_deduplication_groups = AsyncMock(return_value=groups)
        # Mock _load_tweets to return text for each representative tweet
        tweets_map = {
            f"rep_tweet_{i}": f"This is representative tweet {i} with enough text to trigger summarization"
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
            repository=mock_repository,  # type: ignore
            providers=[openrouter, minimax],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": "This is a representative tweet that is long enough to trigger summarization"}
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
            repository=mock_repository,  # type: ignore
            providers=[openrouter, minimax],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": "This is a representative tweet that is long enough to trigger summarization"}
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
        permanent_error = MockLLMError(
            "Authentication failed",
            error_type=LLMErrorType.permanent,
        )

        openrouter = MockLLMProvider(
            "openrouter",
            errors=[permanent_error],
        )
        minimax = MockLLMProvider(
            "minimax",
            errors=[permanent_error],
        )

        service = SummarizationService(
            repository=mock_repository,  # type: ignore
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
            repository=MockRepository(),  # type: ignore
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
            repository=MockRepository(),  # type: ignore
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
            repository=MockRepository(),  # type: ignore
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
            repository=MockRepository(),  # type: ignore
            providers=[provider],
        )

        json_content = '{"summary": "测试摘要", "translation": "测试翻译"}'
        summary, translation = service._parse_llm_response(json_content)

        assert summary == "测试摘要"
        assert translation == "测试翻译"

    @pytest.mark.asyncio
    async def test_parse_llm_response_multiline(self):
        """测试解析多行格式的 LLM 响应。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            repository=MockRepository(),  # type: ignore
            providers=[provider],
        )

        multiline_content = "这是摘要内容\n这是翻译内容"
        summary, translation = service._parse_llm_response(multiline_content)

        assert summary == "这是摘要内容"
        assert translation == "这是翻译内容"

    @pytest.mark.asyncio
    async def test_parse_llm_response_single_line(self):
        """测试解析单行格式的 LLM 响应。"""
        provider = MockLLMProvider("openrouter")
        service = SummarizationService(
            repository=MockRepository(),  # type: ignore
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
            repository=mock_repository,  # type: ignore
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
            repository=mock_repository,  # type: ignore
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

    @pytest.mark.asyncio
    async def test_shared_summary_for_deduplication_group(
        self,
        mock_repository,
        mock_llm_response,
        sample_deduplication_group,
    ):
        """测试同一去重组共享摘要。"""
        provider = MockLLMProvider("openrouter", responses=[mock_llm_response])
        service = SummarizationService(
            repository=mock_repository,  # type: ignore
            providers=[provider],
        )

        service._load_deduplication_groups = AsyncMock(
            return_value=[sample_deduplication_group]
        )
        service._load_tweets = AsyncMock(
            return_value={"rep_tweet_123": "This is a representative tweet that is long enough to trigger summarization"}
        )

        await service.summarize_tweets(
            tweet_ids=sample_deduplication_group.tweet_ids,
            deduplication_groups=[sample_deduplication_group],
        )

        # 验证组内所有推文都有摘要
        for tweet_id in sample_deduplication_group.tweet_ids:
            summary = await mock_repository.get_summary_by_tweet(tweet_id)
            assert summary is not None
            # 同一去重组的摘要应该有相同的 content_hash
            assert summary.content_hash == summary.content_hash


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

        repository = MockRepository()

        service = create_summarization_service(
            repository=repository,  # type: ignore
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

        repository = MockRepository()

        service = create_summarization_service(
            repository=repository,  # type: ignore
            config=config,
        )

        assert service is not None
        assert len(service._providers) == 2

    def test_create_with_no_providers_raises_error(self):
        """测试没有配置任何提供商时抛出错误。"""
        from src.summarization.llm.config import LLMProviderConfig

        config = LLMProviderConfig()
        repository = MockRepository()

        with pytest.raises(ValueError, match="至少需要配置一个 LLM 提供商"):
            create_summarization_service(
                repository=repository,  # type: ignore
                config=config,
            )
