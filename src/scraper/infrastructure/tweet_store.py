"""TweetStore 契约(5 核心方法 + 3 浏览方法)。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.domain.pagination import Feed, Page


@runtime_checkable
class TweetStore(Protocol):
    # —— 与旧 TweetRepository 一致(oracle = 旧 repo) ——
    async def save_tweets(self, tweets: list[Tweet], early_stop_threshold: int = 5) -> SaveResult: ...
    async def batch_check_exists(self, tweet_ids: list[str]) -> set[str]: ...
    async def tweet_exists(self, tweet_id: str) -> bool: ...
    async def get_tweets_by_author(self, author_username: str, limit: int = 100) -> list[Tweet]: ...
    async def get_tweets_by_usernames(self, usernames: list[str], limit: int = 100) -> list[Tweet]: ...

    # —— 三个浏览场景(oracle = 旧 browse/feed service) ——
    async def get_by_day(self, local_date: date, tz_offset_min: int, *,
                         min_text_length: int = 0, limit: int | None = None) -> list[Tweet]: ...
    async def get_by_author_range(self, author_username: str, since: datetime, until: datetime, *,
                                  min_text_length: int = 0, page: int = 1, page_size: int = 50) -> Page[Tweet]: ...
    async def get_feed(self, since: datetime, until: datetime | None = None, *,
                       limit: int = 50) -> Feed[Tweet]: ...
