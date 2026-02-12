"""推文数据验证器。

验证和清理推文数据。
"""

import logging
import re
from collections.abc import Sequence

from datetime import timezone

from returns.result import Failure, Result, Success

from src.scraper.domain.models import Tweet

logger = logging.getLogger(__name__)

# 自定义验证错误类
class ValidationError(Exception):
    """验证错误。

    当推文数据验证失败时抛出。
    """

    def __init__(self, message: str, missing_fields: list[str] | None = None) -> None:
        """初始化验证错误。

        Args:
            message: 错误消息
            missing_fields: 缺失的字段列表
        """
        self.message = message
        self.missing_fields = missing_fields or []
        super().__init__(message)


class TweetValidator:
    """推文数据验证器。

    负责验证推文数据的完整性并清理文本内容。
    """

    # 必需字段列表
    REQUIRED_FIELDS = ["tweet_id", "text", "created_at", "author_username"]

    # 最大文本长度（X Premium 支持最多 25000 字符）
    MAX_TEXT_LENGTH = 25000

    def validate_and_clean(self, tweet: Tweet) -> Result[Tweet, ValidationError]:
        """验证并清理单条推文。

        Args:
            tweet: 待验证的推文

        Returns:
            Result[Tweet, ValidationError]: 成功时返回清理后的推文，失败时返回验证错误
        """
        # 验证必需字段
        validation_error = self._validate_required_fields(tweet)
        if validation_error is not None:
            return Failure(validation_error)

        try:
            # 创建清理后的推文副本
            update_dict: dict = {
                "text": self._clean_text(tweet.text),
                "created_at": self._standardize_datetime(tweet.created_at),
            }
            # 清理被引用推文文本（如有）
            if tweet.referenced_tweet_text:
                update_dict["referenced_tweet_text"] = self._clean_text(
                    tweet.referenced_tweet_text
                )

            cleaned = tweet.model_copy(update=update_dict)

            return Success(cleaned)

        except Exception as e:
            return Failure(ValidationError(f"Failed to clean tweet: {e}"))

    def validate_and_clean_batch(
        self,
        tweets: Sequence[Tweet],
    ) -> list[Result[Tweet, ValidationError]]:
        """批量验证并清理推文。

        Args:
            tweets: 待验证的推文列表

        Returns:
            list[Result[Tweet, ValidationError]]: 每条推文的验证结果
        """
        return [self.validate_and_clean(tweet) for tweet in tweets]

    def _validate_required_fields(self, tweet: Tweet) -> ValidationError | None:
        """验证必需字段。

        Args:
            tweet: 待验证的推文

        Returns:
            ValidationError | None: 如果验证失败返回错误，否则返回 None
        """
        missing_fields = []

        if not tweet.tweet_id:
            missing_fields.append("tweet_id")

        if not tweet.author_username:
            missing_fields.append("author_username")

        # text 可以为空字符串，但不能为 None
        if tweet.text is None:
            missing_fields.append("text")

        if tweet.created_at is None:
            missing_fields.append("created_at")

        if missing_fields:
            return ValidationError(
                f"Missing required fields: {', '.join(missing_fields)}",
                missing_fields,
            )

        return None

    def _clean_text(self, text: str) -> str:
        """清理推文文本。

        - 移除换行符和回车符
        - 移除多余空格
        - 截断过长文本

        Args:
            text: 原始文本

        Returns:
            str: 清理后的文本
        """
        # 移除换行符和回车符，替换为空格
        cleaned = re.sub(r"[\n\r]+", " ", text)

        # 移除多余空格（多个连续空格替换为单个空格）
        cleaned = re.sub(r"\s+", " ", cleaned)

        # 去除首尾空格
        cleaned = cleaned.strip()

        # 截断过长文本
        if len(cleaned) > self.MAX_TEXT_LENGTH:
            cleaned = cleaned[: self.MAX_TEXT_LENGTH]
            logger.debug(f"Truncated text from {len(text)} to {self.MAX_TEXT_LENGTH} characters")

        return cleaned

    def _standardize_datetime(self, dt):
        """标准化日期时间。

        确保 datetime 对象带有时区信息。

        Args:
            dt: 原始 datetime 对象

        Returns:
            datetime: 带时区的 datetime 对象
        """
        # 如果没有时区信息，添加 UTC 时区
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)

        # 已有时区信息，直接返回
        return dt
