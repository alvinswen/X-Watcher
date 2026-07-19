"""文件版 summarization 读门面:组合 FileTweetStore + FileSummaryStore,产
summarization_tools.py 两条读路径(get_unsummarized_tweets 反连接 / get_tweet_origins
原文回查)的同构序列化 dict。parity store 额外暴露 seed_tweets/seed_summaries 供 case 播种。

约定:created_at 经 _dt_to_iso(aware→...+00:00)与 oracle 同构;reference_type .value;
反连接 created_at DESC(契约,NULL 殿后),author 精确匹配,半开区间 [since, until)。"""
from __future__ import annotations

from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any

from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

_MIN = datetime.min.replace(tzinfo=UTC)


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _dt_to_iso(dt: Any) -> str | None:
    return _as_utc(dt).isoformat() if dt is not None else None


class FileSummarizationReadStore:
    def __init__(self, data_root: Path) -> None:
        root = Path(data_root)
        self._tweets = FileTweetStore(root)
        self._summaries = FileSummaryStore(root)

    # ── seed(parity 播种,委派底层 store)──
    async def seed_tweets(self, tweets: Any) -> None:
        await self._tweets.save_tweets(tweets, early_stop_threshold=0)

    async def seed_summaries(self, records: Any) -> None:
        await self._summaries.seed(records)

    # ── read path ① 反连接 ──
    async def get_unsummarized_tweets(self, since: Any = None, until: Any = None, author: Any = None, limit: Any = 50) -> list[dict[str, Any]]:
        clamped = min(max(limit, 1), 200)
        summarized = {s.tweet_id for s in await self._summaries.get_all_summaries()}
        kept = []
        for t in await self._tweets.get_all_tweets():
            if t.tweet_id in summarized:
                continue
            ts = _as_utc(t.created_at) if t.created_at else None
            if since is not None and (ts is None or ts < _as_utc(since)):
                continue
            if until is not None and (ts is None or ts >= _as_utc(until)):
                continue
            if author is not None and t.author_username != author:
                continue
            kept.append(t)
        kept.sort(
            key=lambda t: (t.created_at is not None, _as_utc(t.created_at) if t.created_at else _MIN),
            reverse=True,
        )
        return [self._to_dict(t) for t in kept[:clamped]]

    # ── count ① 反连接 count(preview;不受 limit 截断,复刻反连接谓词)──
    async def count_unsummarized(self, since: Any = None, until: Any = None, author: Any = None) -> int:
        summarized = {s.tweet_id for s in await self._summaries.get_all_summaries()}
        n = 0
        for t in await self._tweets.get_all_tweets():
            if t.tweet_id in summarized:
                continue
            ts = _as_utc(t.created_at) if t.created_at else None
            if since is not None and (ts is None or ts < _as_utc(since)):
                continue
            if until is not None and (ts is None or ts >= _as_utc(until)):
                continue
            if author is not None and t.author_username != author:
                continue
            n += 1
        return n

    # ── count ② 时间窗全部推文 count(reset;含已摘要,无反连接,半开 [since, until))──
    async def count_tweets_in_window(self, since: Any, until: Any) -> int:
        lo = _as_utc(since)
        hi = _as_utc(until)
        n = 0
        for t in await self._tweets.get_all_tweets():
            ts = _as_utc(t.created_at) if t.created_at else None
            if ts is None or ts < lo or ts >= hi:
                continue
            n += 1
        return n

    # ── id-list ① 反连接 id 全集(backfill;复刻 count_unsummarized 反连接谓词,无 author 无 limit)──
    async def list_unsummarized_ids(self, since: Any = None, until: Any = None) -> list[str]:
        """缺摘要推文 id 全集(排除已摘要、since>= / until< 半开窗)。

        无 limit 故返回全集,跨模式按集合等价对账(顺序不设契约;file 端给 tweet_id
        升序确定性序,路由原 SQL 无 order_by 即 DB 任意序)。
        """
        summarized = {s.tweet_id for s in await self._summaries.get_all_summaries()}
        kept = []
        for t in await self._tweets.get_all_tweets():
            if t.tweet_id in summarized:
                continue
            ts = _as_utc(t.created_at) if t.created_at else None
            if since is not None and (ts is None or ts < _as_utc(since)):
                continue
            if until is not None and (ts is None or ts >= _as_utc(until)):
                continue
            kept.append(t.tweet_id)
        return sorted(kept)

    # ── id-list ② 时间窗 id 全集(reset;复刻 count_tweets_in_window 半开窗,无 limit)──
    async def list_tweet_ids_in_window(self, since: Any, until: Any) -> list[str]:
        """时间窗内推文 id 全集(含已摘要,半开 [since, until))。

        无 limit 故返回全集,跨模式按集合等价对账(顺序不设契约;file 端给 tweet_id
        升序确定性序,路由原 SQL 无 order_by 即 DB 任意序)。
        """
        lo = _as_utc(since)
        hi = _as_utc(until)
        kept = []
        for t in await self._tweets.get_all_tweets():
            ts = _as_utc(t.created_at) if t.created_at else None
            if ts is None or ts < lo or ts >= hi:
                continue
            kept.append(t.tweet_id)
        return sorted(kept)

    def _to_dict(self, t: Any) -> dict[str, Any]:
        return {
            "tweet_id": t.tweet_id,
            "text": t.text,
            "author_username": t.author_username,
            "author_display_name": t.author_display_name,
            "reference_type": t.reference_type.value if t.reference_type else None,
            "referenced_tweet_text": t.referenced_tweet_text,
            "referenced_tweet_author_username": t.referenced_tweet_author_username,
            "created_at": _dt_to_iso(t.created_at),
        }

    # ── read path ② origin 回查 ──
    async def get_tweet_origins(self, tweet_ids: Any) -> dict[str, Any]:
        wanted = set(tweet_ids)
        if not wanted:
            return {}
        return {
            t.tweet_id: {
                "text": t.text,
                "referenced_tweet_text": t.referenced_tweet_text,
                "reference_type": t.reference_type.value if t.reference_type else None,
                "referenced_tweet_id": t.referenced_tweet_id,
                "author_username": t.author_username,
                "referenced_tweet_author_username": t.referenced_tweet_author_username,
            }
            for t in await self._tweets.get_all_tweets()
            if t.tweet_id in wanted
        }
