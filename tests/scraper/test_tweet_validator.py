"""TweetValidator 单元测试。

测试推文数据验证和清理功能。
"""

from datetime import UTC, datetime

from returns.result import Failure, Success

from src.scraper.domain.models import Tweet
from src.scraper.validator import TweetValidator


class TestTweetValidator:
    """TweetValidator 测试类。"""

    def test_validate_valid_tweet(self):
        """测试验证有效推文。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="Valid tweet",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)

        assert isinstance(result, Success)
        cleaned = result.unwrap()
        assert cleaned.tweet_id == "123"
        assert cleaned.text == "Valid tweet"

    def test_validate_missing_required_field(self):
        """测试验证缺少必需字段。"""
        validator = TweetValidator()

        # 使用 model_copy 创建一个空 tweet_id 的推文
        tweet = Tweet(
            tweet_id="123",
            text="Valid tweet",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )
        # 手动设置为空字符串
        tweet.tweet_id = ""

        result = validator.validate_and_clean(tweet)

        # 空 tweet_id 应该被验证为无效
        assert isinstance(result, Failure)

    def test_clean_text_removes_newlines(self):
        """测试清理推文文本移除换行符。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="Line 1\nLine 2\rLine 3\r\nLine 4",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        assert "\n" not in cleaned.text
        assert "\r" not in cleaned.text

    def test_clean_text_removes_extra_whitespace(self):
        """测试清理推文文本移除多余空格。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="  Multiple   spaces   between   words  ",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        # 多个空格被替换为单个空格
        assert "   " not in cleaned.text

    def test_long_text_preserved(self):
        """测试长文本不再被截断（X Premium 支持最多 25000 字符）。"""
        validator = TweetValidator()

        # 创建超过 280 字符的推文（模拟 X Premium 长推文）
        long_text = "a" * 1000

        tweet = Tweet(
            tweet_id="123",
            text=long_text,
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        # 1000 字符应该被完整保留
        assert len(cleaned.text) == 1000

    def test_referenced_tweet_text_cleaned(self):
        """测试被引用推文文本也被清理。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="My comment",
            created_at=datetime.now(UTC),
            author_username="testuser",
            referenced_tweet_text="Original  text\nwith  newlines\n\nand  spaces",
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        # 被引用推文文本应该被清理（移除换行和多余空格）
        assert "\n" not in cleaned.referenced_tweet_text
        assert "  " not in cleaned.referenced_tweet_text

    def test_validate_and_clean_multiple_tweets(self):
        """测试验证和清理多条推文。"""
        validator = TweetValidator()

        tweets = [
            Tweet(
                tweet_id=str(i),
                text=f"Tweet {i} with\n newlines",
                created_at=datetime.now(UTC),
                author_username="user",
            )
            for i in range(5)
        ]

        results = validator.validate_and_clean_batch(tweets)

        assert len(results) == 5
        for result in results:
            assert isinstance(result, Success)
            cleaned = result.unwrap()
            assert "\n" not in cleaned.text

    def test_handle_tweet_with_special_characters(self):
        """测试处理包含特殊字符的推文。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="Tweet with emojis 😊 and special chars: <>&\"'",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        assert isinstance(result, Success)

    def test_preserve_url_in_text(self):
        """测试保留文本中的 URL。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="Check out https://example.com for more info",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        assert "https://example.com" in cleaned.text

    def test_standardize_datetime(self):
        """测试标准化日期时间格式。"""
        validator = TweetValidator()

        # 创建不带时区的 datetime
        dt_naive = datetime(2024, 1, 1, 12, 0, 0)

        tweet = Tweet(
            tweet_id="123",
            text="Test",
            created_at=dt_naive,
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        # 清理后应该带有时区信息
        assert cleaned.created_at.tzinfo is not None

    def test_empty_text_handling(self):
        """测试处理空文本。"""
        validator = TweetValidator()

        tweet = Tweet(
            tweet_id="123",
            text="   ",
            created_at=datetime.now(UTC),
            author_username="testuser",
        )

        result = validator.validate_and_clean(tweet)
        # 空白文本应该被保留
        assert isinstance(result, Success)

    def test_tweet_with_media_preserved(self):
        """测试媒体信息被保留。"""
        validator = TweetValidator()

        from src.scraper.domain.models import Media

        tweet = Tweet(
            tweet_id="123",
            text="Tweet with media",
            created_at=datetime.now(UTC),
            author_username="testuser",
            media=[
                Media(
                    media_key="media_1",
                    type="photo",
                    url="https://example.com/img.jpg",
                )
            ],
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        assert cleaned.media is not None
        assert len(cleaned.media) == 1
        assert cleaned.media[0].media_key == "media_1"

    def test_tweet_with_reference_preserved(self):
        """测试引用信息被保留。"""
        validator = TweetValidator()

        from src.scraper.domain.models import ReferenceType

        tweet = Tweet(
            tweet_id="123",
            text="Retweet",
            created_at=datetime.now(UTC),
            author_username="testuser",
            referenced_tweet_id="456",
            reference_type=ReferenceType.retweeted,
        )

        result = validator.validate_and_clean(tweet)
        cleaned = result.unwrap()

        assert cleaned.referenced_tweet_id == "456"
        assert cleaned.reference_type == ReferenceType.retweeted
