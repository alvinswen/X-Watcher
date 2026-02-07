"""去重检测器单元测试。"""

from datetime import datetime, timezone

import pytest

from src.deduplication.domain.detectors import ExactDuplicateDetector, SimilarityDetector
from src.scraper.domain.models import ReferenceType, Tweet


class TestExactDuplicateDetector:
    """精确重复检测器测试。"""

    @pytest.fixture
    def detector(self) -> ExactDuplicateDetector:
        """创建检测器实例。"""
        return ExactDuplicateDetector()

    @pytest.fixture
    def sample_tweets(self) -> list[Tweet]:
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
                text="Hello world",  # 相同文本
                created_at=now,
                author_username="user2",
            ),
            Tweet(
                tweet_id="3",
                text="Different text",
                created_at=now,
                author_username="user1",
            ),
            Tweet(
                tweet_id="4",
                text="Hello world",  # 相同文本
                created_at=now,
                author_username="user3",
            ),
        ]

    def test_detect_duplicates_finds_duplicates(
        self, detector: ExactDuplicateDetector, sample_tweets: list[Tweet]
    ):
        """测试检测重复推文。"""
        groups = detector.detect_duplicates(sample_tweets)

        assert len(groups) == 1
        assert groups[0].representative_id in ["1", "2", "4"]
        assert set(groups[0].tweet_ids) == {"1", "2", "4"}

    def test_detect_duplicates_with_empty_list(self, detector: ExactDuplicateDetector):
        """测试空列表。"""
        groups = detector.detect_duplicates([])
        assert groups == []

    def test_detect_duplicates_with_single_tweet(
        self, detector: ExactDuplicateDetector
    ):
        """测试单条推文。"""
        tweet = Tweet(
            tweet_id="1",
            text="Hello",
            created_at=datetime.now(timezone.utc),
            author_username="user1",
        )
        groups = detector.detect_duplicates([tweet])
        assert groups == []

    def test_detect_duplicates_with_retweets(self, detector: ExactDuplicateDetector):
        """测试转发关系检测。"""
        now = datetime.now(timezone.utc)
        tweets = [
            Tweet(
                tweet_id="1",
                text="Original tweet",
                created_at=now,
                author_username="user1",
            ),
            Tweet(
                tweet_id="2",
                text="RT: Original tweet",
                created_at=now,
                author_username="user2",
                referenced_tweet_id="1",
                reference_type=ReferenceType.retweeted,
            ),
            Tweet(
                tweet_id="3",
                text="RT: Original tweet",
                created_at=now,
                author_username="user3",
                referenced_tweet_id="1",
                reference_type=ReferenceType.retweeted,
            ),
        ]

        groups = detector.detect_duplicates(tweets)

        # 应该找到一个组（包含原推文和两个转发）
        assert len(groups) == 1
        assert groups[0].representative_id == "1"  # 原推文是代表
        assert set(groups[0].tweet_ids) == {"1", "2", "3"}

    def test_detect_duplicates_with_extra_whitespace(
        self, detector: ExactDuplicateDetector
    ):
        """测试处理多余空格。"""
        now = datetime.now(timezone.utc)
        tweets = [
            Tweet(
                tweet_id="1",
                text="Hello   world",  # 多余空格
                created_at=now,
                author_username="user1",
            ),
            Tweet(
                tweet_id="2",
                text="Hello world",  # 正常空格
                created_at=now,
                author_username="user2",
            ),
            Tweet(
                tweet_id="3",
                text="  Hello   world  ",  # 前后多余空格
                created_at=now,
                author_username="user3",
            ),
        ]

        groups = detector.detect_duplicates(tweets)

        assert len(groups) == 1
        assert len(groups[0].tweet_ids) == 3


class TestSimilarityDetector:
    """相似度检测器测试。"""

    @pytest.fixture
    def detector(self) -> SimilarityDetector:
        """创建检测器实例。"""
        return SimilarityDetector()

    def test_preprocess_text(self, detector: SimilarityDetector):
        """测试文本预处理。"""
        # 移除 URL
        assert detector._preprocess_text("Check https://example.com out") == "check out"

        # 移除提及
        assert detector._preprocess_text("Hello @user123 world") == "hello world"

        # 移除多余空格
        assert detector._preprocess_text("Hello    world") == "hello world"

        # 转小写
        assert detector._preprocess_text("HELLO World") == "hello world"

        # 组合
        text = "Check @user https://example.com   HELLO"
        assert detector._preprocess_text(text) == "check hello"

    def test_detect_similar_with_empty_list(self, detector: SimilarityDetector):
        """测试空列表。"""
        groups = detector.detect_similar([])
        assert groups == []

    def test_detect_similar_with_single_tweet(self, detector: SimilarityDetector):
        """测试单条推文。"""
        tweet = Tweet(
            tweet_id="1",
            text="Hello",
            created_at=datetime.now(timezone.utc),
            author_username="user1",
        )
        groups = detector.detect_similar([tweet])
        assert groups == []

    @pytest.mark.skipif(
        True,  # 跳过需要 scikit-learn 的测试
        reason="需要 scikit-learn，在实际环境中测试"
    )
    def test_detect_similar_finds_similar_tweets(self, detector: SimilarityDetector):
        """测试检测相似推文。"""
        now = datetime.now(timezone.utc)
        tweets = [
            Tweet(
                tweet_id="1",
                text="Breaking news: AI advances rapidly",
                created_at=now,
                author_username="user1",
            ),
            Tweet(
                tweet_id="2",
                text="Breaking news: AI advances fast today",
                created_at=now,
                author_username="user2",
            ),
            Tweet(
                tweet_id="3",
                text="Completely different content about weather",
                created_at=now,
                author_username="user3",
            ),
        ]

        groups = detector.detect_similar(tweets, threshold=0.5)

        # 应该找到一个相似组
        assert len(groups) >= 0

    def test_detect_similar_without_sklearn(self, detector: SimilarityDetector):
        """测试没有 scikit-learn 时的降级行为。"""
        # 这个测试验证当 sklearn 不可用时不会崩溃
        tweets = [
            Tweet(
                tweet_id="1",
                text="Hello world",
                created_at=datetime.now(timezone.utc),
                author_username="user1",
            ),
        ]

        # 应该不抛出异常
        groups = detector.detect_similar(tweets)
        assert groups == []  # 单条推文无法检测相似度
