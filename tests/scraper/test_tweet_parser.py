"""TweetParser 单元测试。

测试推文数据解析功能。
"""

from datetime import datetime, timezone

import pytest

from src.scraper.domain.models import Media, ReferenceType, Tweet
from src.scraper.parser import TweetParser


class TestTweetParser:
    """TweetParser 测试类。"""

    def test_parse_simple_tweet(self):
        """测试解析简单推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "This is a simple tweet.",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user123",
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ]
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 1
        assert tweets[0].tweet_id == "1234567890"
        assert tweets[0].text == "This is a simple tweet."
        assert tweets[0].author_username == "testuser"
        assert tweets[0].author_display_name == "Test User"

    def test_parse_tweet_with_media(self):
        """测试解析带媒体的推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "Tweet with image.",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user123",
                    "attachments": {
                        "media_keys": ["media_123"],
                    },
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ],
                "media": [
                    {
                        "media_key": "media_123",
                        "type": "photo",
                        "url": "https://example.com/image.jpg",
                        "width": 800,
                        "height": 600,
                    }
                ],
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 1
        assert tweets[0].media is not None
        assert len(tweets[0].media) == 1
        assert tweets[0].media[0].type == "photo"
        assert tweets[0].media[0].url == "https://example.com/image.jpg"

    def test_parse_tweet_with_referenced_tweet(self):
        """测试解析带引用的推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "RT: Original tweet",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user123",
                    "referenced_tweets": [
                        {
                            "type": "retweeted",
                            "id": "9876543210",
                        }
                    ],
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ],
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 1
        assert tweets[0].referenced_tweet_id == "9876543210"
        assert tweets[0].reference_type == ReferenceType.retweeted

    def test_parse_multiple_tweets(self):
        """测试解析多条推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1",
                    "text": "Tweet 1",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user1",
                },
                {
                    "id": "2",
                    "text": "Tweet 2",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user2",
                },
            ],
            "includes": {
                "users": [
                    {"id": "user1", "username": "user1", "name": "User 1"},
                    {"id": "user2", "username": "user2", "name": "User 2"},
                ]
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 2
        assert tweets[0].tweet_id == "1"
        assert tweets[1].tweet_id == "2"

    def test_parse_with_missing_author(self):
        """测试解析缺少作者的推文（应跳过并记录警告）。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "Tweet without author.",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "unknown_user",
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ]
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        # 缺少作者的推文应被跳过
        assert len(tweets) == 0

    def test_parse_quoted_tweet(self):
        """测试解析引用推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "Quoting a tweet",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user123",
                    "referenced_tweets": [
                        {
                            "type": "quoted",
                            "id": "9876543210",
                        }
                    ],
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ],
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 1
        assert tweets[0].reference_type == ReferenceType.quoted

    def test_parse_replied_tweet(self):
        """测试解析回复推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "@someone Reply",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user123",
                    "referenced_tweets": [
                        {
                            "type": "replied_to",
                            "id": "9876543210",
                        }
                    ],
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ],
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 1
        assert tweets[0].reference_type == ReferenceType.replied_to

    def test_parse_with_empty_data(self):
        """测试解析空数据。"""
        parser = TweetParser()

        raw_data = {
            "data": [],
            "includes": {"users": []},
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 0

    def test_parse_tweet_without_display_name(self):
        """测试解析没有显示名称的推文。"""
        parser = TweetParser()

        raw_data = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "Tweet",
                    "created_at": "2024-01-01T12:00:00.000Z",
                    "author_id": "user123",
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        # name 字段缺失
                    }
                ]
            },
        }

        tweets = parser.parse_tweet_response(raw_data)

        assert len(tweets) == 1
        assert tweets[0].author_username == "testuser"
        assert tweets[0].author_display_name is None
