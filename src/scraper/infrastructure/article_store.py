"""ArticleStore 契约(5 方法)。两实现共享:oracle(vendored 旧 repo)与文件 candidate。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.scraper.domain.models import Article


@runtime_checkable
class ArticleStore(Protocol):
    async def article_exists(self, tweet_id: str) -> bool: ...
    async def save_article(self, article: Article) -> bool: ...
    async def get_article(self, tweet_id: str) -> Article | None: ...
    async def get_articles_by_author(self, username: str, *,
                                     limit: int = 50, offset: int = 0) -> list[Article]: ...
    async def count_articles(self) -> int: ...
