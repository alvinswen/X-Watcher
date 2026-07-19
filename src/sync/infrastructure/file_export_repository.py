# src/sync/infrastructure/file_export_repository.py
"""文件版 Export 门面:组合已迁 File*Store,产 serializers 同构的序列化 dict。

parity store 额外暴露 seed_*(委派各底层 store 的 seed/save)供 case 播种。"""

from __future__ import annotations

from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.scraper.infrastructure.file_article_repository import FileArticleStore
from src.sync.infrastructure import export_serializers as S


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class FileExportStore:
    def __init__(self, data_root: Path) -> None:
        root = Path(data_root)
        self._follows = FileFollowStore(root)
        self._tweets = FileTweetStore(root)
        self._summaries = FileSummaryStore(root)
        self._articles = FileArticleStore(root)

    # ── seed(parity 播种,委派底层 store)──
    async def seed_follows(self, follows: Any) -> None:
        await self._follows.seed(follows)

    async def seed_tweets(self, tweets: Any) -> None:
        await self._tweets.save_tweets(tweets, early_stop_threshold=0)

    async def seed_summaries(self, records: Any) -> None:
        await self._summaries.seed(records)

    async def seed_articles(self, articles: Any) -> None:
        await self._articles.seed(articles)

    # ── export(序列化 dict)──
    async def export_follows(self) -> list[dict[str, Any]]:
        follows = await self._follows.get_all_follows(include_inactive=True)
        return [S.follow_to_export_dict(f) for f in follows]

    async def export_tweets(
        self, since: Any = None, until: Any = None, authors: Any = None
    ) -> list[dict[str, Any]]:
        tweets = await self._tweets.get_all_tweets()
        authors_set = set(authors) if authors else None
        out = []
        for t in tweets:
            ts = _as_utc(t.created_at)
            if since is not None and ts < _as_utc(since):
                continue
            if until is not None and ts > _as_utc(until):  # until 闭区间(≡ 旧 <=)
                continue
            if authors_set is not None and t.author_username not in authors_set:
                continue
            out.append(S.tweet_to_export_dict(t))
        return out

    async def export_summaries(self, tweet_ids: Any = None) -> list[dict[str, Any]]:
        summaries = await self._summaries.get_all_summaries()
        if tweet_ids is not None:
            wanted = set(tweet_ids)
            summaries = [s for s in summaries if s.tweet_id in wanted]
        return [S.summary_to_export_dict(s) for s in summaries]

    async def export_articles(self, tweet_ids: Any = None) -> list[dict[str, Any]]:
        articles = await self._articles.get_all_articles()
        if tweet_ids is not None:
            wanted = set(tweet_ids)
            articles = [a for a in articles if a.tweet_id in wanted]
        return [S.article_to_export_dict(a) for a in articles]
