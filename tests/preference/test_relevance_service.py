"""RelevanceService 单元测试。

测试推文相关性计算服务。
"""

from datetime import datetime, timezone

import pytest

from src.preference.domain.models import FilterType
from src.preference.services.relevance_service import (
    RelevanceService,
    KeywordRelevanceService,
    RelevanceServiceError,
)
from src.scraper.domain.models import Tweet


class TestKeywordRelevanceService:
    """KeywordRelevanceService 测试类。"""

    @pytest.fixture
    def service(self) -> KeywordRelevanceService:
        """创建服务实例。"""
        return KeywordRelevanceService()

    @pytest.fixture
    def sample_tweet(self) -> Tweet:
        """创建示例推文。"""
        return Tweet(
            tweet_id="123",
            text="This is a tweet about AI and machine learning. Transformers are amazing!",
            created_at=datetime.now(timezone.utc),
            author_username="techuser",
        )

    async def test_calculate_relevance_with_matching_keywords(self, service, sample_tweet):
        """测试包含匹配关键词时返回高分。"""
        # Act
        result = await service.calculate_relevance(
            tweet=sample_tweet,
            keywords=["AI", "transformers", "LLM"]
        )

        # Assert - 应该有较高分数，因为包含多个关键词
        assert result > 0.5
        assert result <= 1.0

    async def test_calculate_relevance_with_no_match(self, service, sample_tweet):
        """测试没有匹配关键词时返回低分。"""
        # Act
        result = await service.calculate_relevance(
            tweet=sample_tweet,
            keywords=["blockchain", "crypto", "NFT"]
        )

        # Assert - 应该返回 0
        assert result == 0.0

    async def test_calculate_relevance_case_insensitive(self, service, sample_tweet):
        """测试匹配不区分大小写。"""
        # Act - 使用大写关键词
        result_upper = await service.calculate_relevance(
            tweet=sample_tweet,
            keywords=["AI", "MACHINE"]
        )

        # Act - 使用小写关键词
        result_lower = await service.calculate_relevance(
            tweet=sample_tweet,
            keywords=["ai", "machine"]
        )

        # Assert - 结果应该相同
        assert result_upper == result_lower
        assert result_upper > 0

    async def test_calculate_relevance_with_empty_keywords(self, service, sample_tweet):
        """测试空关键词列表返回 0。"""
        # Act
        result = await service.calculate_relevance(
            tweet=sample_tweet,
            keywords=[]
        )

        # Assert
        assert result == 0.0

    async def test_calculate_relevance_counts_multiple_occurrences(self, service):
        """测试多次出现的关键词权重更高。"""
        # Arrange - 创建包含重复关键词的推文
        tweet = Tweet(
            tweet_id="123",
            text="AI AI AI machine learning AI transformers",
            created_at=datetime.now(timezone.utc),
            author_username="techuser",
        )

        # Act
        result = await service.calculate_relevance(
            tweet=tweet,
            keywords=["AI"]
        )

        # Assert - "AI" 出现 4 次，应该有较高分数
        assert result > 0.3

    async def test_calculate_relevance_partial_word_match(self, service):
        """测试部分单词匹配（例如 "machine" 匹配 "machine learning"）。"""
        # Arrange
        tweet = Tweet(
            tweet_id="123",
            text="I love machine learning and deep learning",
            created_at=datetime.now(timezone.utc),
            author_username="techuser",
        )

        # Act
        result = await service.calculate_relevance(
            tweet=tweet,
            keywords=["learn"]
        )

        # Assert - 应该匹配 "learning" 中的 "learn"
        assert result > 0

    async def test_calculate_relevance_with_special_characters(self, service):
        """测试包含特殊字符的推文。"""
        # Arrange
        tweet = Tweet(
            tweet_id="123",
            text="Check out this AI/Machine Learning project! #AI #tech",
            created_at=datetime.now(timezone.utc),
            author_username="techuser",
        )

        # Act
        result = await service.calculate_relevance(
            tweet=tweet,
            keywords=["AI", "tech"]
        )

        # Assert - 应该匹配，忽略特殊字符
        assert result > 0


class TestRelevanceServiceError:
    """RelevanceServiceError 测试类。"""

    def test_error_is_exception(self):
        """测试错误类是 Exception 的子类。"""
        error = RelevanceServiceError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"
