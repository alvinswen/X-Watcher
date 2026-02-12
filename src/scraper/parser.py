"""推文数据解析器。

解析 X 平台 API v2 响应格式为 Tweet 模型。
"""

import logging
from datetime import timezone

from src.scraper.domain.models import Media, ReferenceType, Tweet

logger = logging.getLogger(__name__)


class TweetParser:
    """推文数据解析器。

    负责将 Twitter API v2 的 JSON 响应解析为 Tweet 领域模型。
    """

    def parse_tweet_response(self, raw_data: dict) -> list[Tweet]:
        """解析推文响应。

        Args:
            raw_data: Twitter API v2 响应的原始数据

        Returns:
            list[Tweet]: 解析后的推文列表，无效数据会被跳过
        """
        tweets: list[Tweet] = []

        # 获取推文数据
        data_list = raw_data.get("data", [])
        includes = raw_data.get("includes", {})

        # 构建用户 ID 到用户信息的映射
        users_map = {}
        for user in includes.get("users", []):
            users_map[user["id"]] = {
                "username": user.get("username"),
                "name": user.get("name"),
            }

        # 构建媒体 key 到媒体信息的映射
        media_map = {}
        for media in includes.get("media", []):
            media_map[media["media_key"]] = {
                "type": media.get("type"),
                "url": media.get("url"),
                "preview_image_url": media.get("preview_image_url"),
                "width": media.get("width"),
                "height": media.get("height"),
                "alt_text": media.get("alt_text"),
            }

        # 解析每条推文
        for tweet_data in data_list:
            try:
                tweet = self._parse_single_tweet(
                    tweet_data, users_map, media_map
                )
                if tweet is not None:
                    tweets.append(tweet)
            except Exception as e:
                logger.warning(f"Failed to parse tweet {tweet_data.get('id')}: {e}")
                continue

        return tweets

    def _parse_single_tweet(
        self,
        tweet_data: dict,
        users_map: dict,
        media_map: dict,
    ) -> Tweet | None:
        """解析单条推文。

        Args:
            tweet_data: 单条推文的原始数据
            users_map: 用户 ID 到用户信息的映射
            media_map: 媒体 key 到媒体信息的映射

        Returns:
            Tweet | None: 解析后的推文，如果解析失败返回 None
        """
        # 获取作者信息
        author_id = tweet_data.get("author_id")
        if author_id is None:
            logger.warning(f"Tweet {tweet_data.get('id')} missing author_id")
            return None

        author_info = users_map.get(author_id)
        if author_info is None:
            logger.warning(f"Tweet {tweet_data.get('id')} author {author_id} not found in includes")
            return None

        author_username = author_info.get("username")
        if author_username is None:
            logger.warning(f"Tweet {tweet_data.get('id')} author missing username")
            return None

        # 解析引用关系
        referenced_tweet_id = None
        reference_type = None
        referenced_tweets = tweet_data.get("referenced_tweets", [])
        if referenced_tweets:
            ref = referenced_tweets[0]
            referenced_tweet_id = ref.get("id")
            try:
                reference_type = ReferenceType(ref.get("type"))
            except ValueError:
                logger.warning(f"Unknown reference type: {ref.get('type')}")
                reference_type = None

        # 解析媒体
        media = None
        attachments = tweet_data.get("attachments", {})
        media_keys = attachments.get("media_keys", [])
        if media_keys:
            media = self._parse_media(media_keys, media_map)

        # 解析被引用推文的完整文本和媒体
        referenced_tweet_text = tweet_data.get("referenced_tweet_text")

        referenced_tweet_media = None
        ref_media_data = tweet_data.get("referenced_tweet_media")
        if ref_media_data and isinstance(ref_media_data, list):
            referenced_tweet_media = [
                Media(
                    media_key=m.get("media_key", ""),
                    type=m.get("type", "unknown"),
                    url=m.get("url"),
                    preview_image_url=m.get("preview_image_url"),
                    width=m.get("width"),
                    height=m.get("height"),
                    alt_text=m.get("alt_text"),
                )
                for m in ref_media_data
                if isinstance(m, dict)
            ]
            if not referenced_tweet_media:
                referenced_tweet_media = None

        # 解析创建时间
        created_at_str = tweet_data.get("created_at")
        if created_at_str:
            # Twitter API 返回的时间格式: 2024-01-01T12:00:00.000Z
            # 转换为 datetime 对象
            created_at = self._parse_datetime(created_at_str)
        else:
            logger.warning(f"Tweet {tweet_data.get('id')} missing created_at")
            return None

        return Tweet(
            tweet_id=tweet_data["id"],
            text=tweet_data.get("text", ""),
            created_at=created_at,
            author_username=author_username,
            author_display_name=author_info.get("name"),
            referenced_tweet_id=referenced_tweet_id,
            reference_type=reference_type,
            media=media if media else None,
            referenced_tweet_text=referenced_tweet_text,
            referenced_tweet_media=referenced_tweet_media,
        )

    def _parse_media(
        self,
        media_keys: list[str],
        media_map: dict,
    ) -> list[Media]:
        """解析媒体附件。

        Args:
            media_keys: 媒体 key 列表
            media_map: 媒体 key 到媒体信息的映射

        Returns:
            list[Media]: 媒体列表
        """
        media_list = []
        for key in media_keys:
            media_info = media_map.get(key)
            if media_info is None:
                continue

            media_list.append(
                Media(
                    media_key=key,
                    type=media_info.get("type", "unknown"),
                    url=media_info.get("url"),
                    preview_image_url=media_info.get("preview_image_url"),
                    width=media_info.get("width"),
                    height=media_info.get("height"),
                    alt_text=media_info.get("alt_text"),
                )
            )

        return media_list

    def _parse_datetime(self, datetime_str: str):
        """解析日期时间字符串。

        Args:
            datetime_str: ISO 8601 格式的日期时间字符串

        Returns:
            datetime: 带时区的 datetime 对象
        """
        # 处理 Twitter API 的日期格式
        # 2024-01-01T12:00:00.000Z
        if datetime_str.endswith("Z"):
            datetime_str = datetime_str[:-1] + "+00:00"

        from datetime import datetime

        # 使用 fromisoformat 解析
        dt = datetime.fromisoformat(datetime_str)

        # 确保有时区信息
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt
