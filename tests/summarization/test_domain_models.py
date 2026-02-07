"""摘要领域模型单元测试。

测试摘要相关的 Pydantic 数据模型。
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.summarization.domain.models import (
    CostStats,
    LLMErrorType,
    LLMResponse,
    PromptConfig,
    SummaryRecord,
    SummaryResult,
)


class TestLLMResponse:
    """LLM 响应模型测试。"""

    def test_create_valid_llm_response(self):
        """测试创建有效的 LLM 响应。"""
        response = LLMResponse(
            content="这是一个测试摘要",
            model="claude-sonnet-4.5",
            provider="openrouter",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
        )
        assert response.content == "这是一个测试摘要"
        assert response.provider == "openrouter"
        assert response.total_tokens == 150

    def test_llm_response_with_minimax_provider(self):
        """测试 MiniMax 提供商的响应。"""
        response = LLMResponse(
            content="翻译结果",
            model="m2.1",
            provider="minimax",
            prompt_tokens=80,
            completion_tokens=40,
            total_tokens=120,
            cost_usd=0.0008,
        )
        assert response.provider == "minimax"
        assert response.model == "m2.1"

    def test_llm_response_requires_positive_tokens(self):
        """测试 token 数必须为正数。"""
        with pytest.raises(ValidationError):
            LLMResponse(
                content="测试",
                model="test",
                provider="openrouter",
                prompt_tokens=-1,  # 无效
                completion_tokens=50,
                total_tokens=49,
                cost_usd=0.001,
            )

    def test_llm_response_total_tokens_matches_sum(self):
        """测试总 token 数应等于输入加输出。"""
        response = LLMResponse(
            content="测试",
            model="test",
            provider="openrouter",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,  # 匹配
            cost_usd=0.001,
        )
        assert response.total_tokens == response.prompt_tokens + response.completion_tokens

    def test_llm_response_provider_validation(self):
        """测试提供商必须为有效值。"""
        with pytest.raises(ValidationError):
            LLMResponse(
                content="测试",
                model="test",
                provider="invalid_provider",  # 无效
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.001,
            )


class TestSummaryRecord:
    """摘要记录模型测试。"""

    @pytest.fixture
    def sample_record_data(self):
        """示例摘要记录数据。"""
        return {
            "summary_id": "550e8400-e29b-41d4-a716-446655440000",
            "tweet_id": "1234567890",
            # 50 字摘要（符合最小长度要求）
            "summary_text": "这是一条关于AI技术突破的推文摘要，内容涵盖了最新的深度学习模型在自然语言处理领域的重大进展，以及其对未来科技发展的深远影响",
            "translation_text": "This is a summary of a tweet about AI breakthrough",
            "model_provider": "openrouter",
            "model_name": "claude-sonnet-4.5",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300,
            "cost_usd": 0.002,
            "cached": False,
            "content_hash": "abc123def456",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def test_create_valid_summary_record(self, sample_record_data):
        """测试创建有效的摘要记录。"""
        record = SummaryRecord(**sample_record_data)
        assert record.summary_id == sample_record_data["summary_id"]
        assert record.tweet_id == sample_record_data["tweet_id"]
        assert record.summary_text == sample_record_data["summary_text"]
        assert record.model_provider == "openrouter"

    def test_summary_record_without_translation(self, sample_record_data):
        """测试没有翻译的摘要记录。"""
        sample_record_data.pop("translation_text")
        record = SummaryRecord(**sample_record_data)
        assert record.translation_text is None

    def test_summary_record_with_cached_true(self, sample_record_data):
        """测试缓存的摘要记录。"""
        sample_record_data["cached"] = True
        record = SummaryRecord(**sample_record_data)
        assert record.cached is True

    def test_summary_record_summary_text_length_validation(self, sample_record_data):
        """测试摘要文本长度限制（1-500 字）。"""
        # 太短（空字符串）
        sample_record_data["summary_text"] = ""
        with pytest.raises(ValidationError):
            SummaryRecord(**sample_record_data)

        # 太长
        sample_record_data["summary_text"] = "a" * 501
        with pytest.raises(ValidationError):
            SummaryRecord(**sample_record_data)

    def test_summary_record_valid_summary_text_length(self, sample_record_data):
        """测试有效的摘要文本长度。"""
        # 边界值测试
        sample_record_data["summary_text"] = "a"  # 最小值
        record = SummaryRecord(**sample_record_data)
        assert len(record.summary_text) == 1

        sample_record_data["summary_text"] = "a" * 500  # 最大值
        record = SummaryRecord(**sample_record_data)
        assert len(record.summary_text) == 500

        # 测试短推文原文（智能长度策略）
        sample_record_data["summary_text"] = "Short tweet"
        sample_record_data["is_generated_summary"] = False
        record = SummaryRecord(**sample_record_data)
        assert record.summary_text == "Short tweet"
        assert record.is_generated_summary is False


class TestSummaryResult:
    """摘要处理结果模型测试。"""

    def test_create_valid_summary_result(self):
        """测试创建有效的处理结果。"""
        result = SummaryResult(
            total_tweets=10,
            total_groups=5,
            cache_hits=3,
            cache_misses=2,
            total_tokens=1500,
            total_cost_usd=0.015,
            providers_used={"openrouter": 3, "minimax": 2},
            processing_time_ms=5000,
        )
        assert result.total_tweets == 10
        assert result.cache_hits + result.cache_misses == result.total_groups
        assert "openrouter" in result.providers_used

    def test_summary_result_cache_calculation(self):
        """测试缓存统计计算。"""
        result = SummaryResult(
            total_tweets=100,
            total_groups=50,
            cache_hits=30,
            cache_misses=20,
            total_tokens=10000,
            total_cost_usd=0.1,
            providers_used={"openrouter": 20},
            processing_time_ms=30000,
        )
        cache_hit_rate = result.cache_hits / result.total_groups
        assert cache_hit_rate == 0.6  # 30/50

    def test_summary_result_multiple_providers(self):
        """测试多个提供商的使用统计。"""
        result = SummaryResult(
            total_tweets=20,
            total_groups=10,
            cache_hits=5,
            cache_misses=5,
            total_tokens=2000,
            total_cost_usd=0.02,
            providers_used={
                "openrouter": 3,
                "minimax": 1,
                "open_source": 1,
            },
            processing_time_ms=10000,
        )
        assert len(result.providers_used) == 3
        assert result.providers_used["openrouter"] == 3

    def test_summary_result_cost_calculation(self):
        """测试成本计算。"""
        result = SummaryResult(
            total_tweets=50,
            total_groups=25,
            cache_hits=10,
            cache_misses=15,
            total_tokens=5000,
            total_cost_usd=0.05,
            providers_used={"openrouter": 15},
            processing_time_ms=15000,
        )
        cost_per_1k_tokens = result.total_cost_usd / (result.total_tokens / 1000)
        assert cost_per_1k_tokens == 0.01  # 0.05 / 5


class TestCostStats:
    """成本统计模型测试。"""

    def test_create_valid_cost_stats(self):
        """测试创建有效的成本统计。"""
        stats = CostStats(
            total_cost_usd=0.1,
            total_tokens=10000,
            prompt_tokens=7000,
            completion_tokens=3000,
            provider_breakdown={
                "openrouter": {"cost_usd": 0.08, "tokens": 8000},
                "minimax": {"cost_usd": 0.02, "tokens": 2000},
            },
        )
        assert stats.total_cost_usd == 0.1
        assert len(stats.provider_breakdown) == 2

    def test_cost_stats_with_date_range(self):
        """测试带日期范围的成本统计。"""
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 1, 31, tzinfo=timezone.utc)
        stats = CostStats(
            start_date=start,
            end_date=end,
            total_cost_usd=0.5,
            total_tokens=50000,
            prompt_tokens=35000,
            completion_tokens=15000,
            provider_breakdown={"openrouter": {"cost_usd": 0.5, "tokens": 50000}},
        )
        assert stats.start_date == start
        assert stats.end_date == end

    def test_cost_stats_token_breakdown(self):
        """测试 token 分解统计。"""
        stats = CostStats(
            total_cost_usd=0.03,
            total_tokens=3000,
            prompt_tokens=2000,
            completion_tokens=1000,
            provider_breakdown={"minimax": {"cost_usd": 0.03, "tokens": 3000}},
        )
        assert stats.total_tokens == stats.prompt_tokens + stats.completion_tokens


class TestLLMErrorType:
    """LLM 错误类型枚举测试。"""

    def test_error_type_values(self):
        """测试错误类型枚举值。"""
        assert LLMErrorType.temporary == "temporary"
        assert LLMErrorType.permanent == "permanent"

    def test_error_type_comparison(self):
        """测试错误类型比较。"""
        assert LLMErrorType.temporary == "temporary"
        assert LLMErrorType.permanent == "permanent"
        assert LLMErrorType.temporary != LLMErrorType.permanent


class TestPromptConfig:
    """Prompt 配置模型测试。"""

    def test_default_prompt_config(self):
        """测试默认 Prompt 配置。"""
        config = PromptConfig()
        assert "请提取以下推文的关键信息" in config.summary_prompt
        assert "请将以下英文推文翻译为中文" in config.translation_prompt

    def test_format_summary_prompt(self):
        """测试格式化摘要 Prompt。"""
        config = PromptConfig()
        tweet_text = "Breaking news: AI model achieves new milestone"
        formatted = config.format_summary(tweet_text)
        assert tweet_text in formatted
        assert "请提取以下推文的关键信息" in formatted

    def test_format_translation_prompt(self):
        """测试格式化翻译 Prompt。"""
        config = PromptConfig()
        tweet_text = "This is a test tweet about technology"
        formatted = config.format_translation(tweet_text)
        assert tweet_text in formatted
        assert "请将以下英文推文翻译为中文" in formatted

    def test_custom_summary_prompt(self):
        """测试自定义摘要 Prompt。"""
        custom_prompt = "自定义摘要模板：{tweet_text}"
        config = PromptConfig(summary_prompt=custom_prompt)
        formatted = config.format_summary("测试内容")
        assert "自定义摘要模板：" in formatted
        assert "测试内容" in formatted

    def test_custom_translation_prompt(self):
        """测试自定义翻译 Prompt。"""
        custom_prompt = "自定义翻译模板：{tweet_text}"
        config = PromptConfig(translation_prompt=custom_prompt)
        formatted = config.format_translation("test content")
        assert "自定义翻译模板：" in formatted
        assert "test content" in formatted
