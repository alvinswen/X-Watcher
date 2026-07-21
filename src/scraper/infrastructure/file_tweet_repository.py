"""文件版 TweetStore 实现。"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.domain.pagination import Feed, Page
from src.storage import paths, views
from src.storage.atomic import shard_lock
from src.storage.index import TweetIdIndex
from src.storage.jsonl_store import read_shard, upsert

# oracle/ORM 无 article_preview 列;本期不持久化以保持与 oracle parity。
# 持久化 article_preview 为未来 changed 增强(走 truth-change 授权)。
_PERSISTED_EXCLUDE = {"article_preview"}


def _to_record(tweet: Tweet) -> dict[str, Any]:
    t = tweet
    if t.created_at.tzinfo is None:
        t = t.model_copy(update={"created_at": t.created_at.replace(tzinfo=UTC)})
    return t.model_dump(mode="json", exclude=_PERSISTED_EXCLUDE)


def _to_domain(record: dict[str, Any]) -> Tweet:
    return Tweet(**record)


def _parse(record: dict[str, Any]) -> datetime:
    return paths.as_utc(datetime.fromisoformat(record["created_at"]))


class FileTweetStore:
    def __init__(self, data_root: Path, index: TweetIdIndex | None = None) -> None:
        self._root = Path(data_root)
        self._index: TweetIdIndex | None = index

    @property
    def _idx(self) -> TweetIdIndex:
        if self._index is None:
            self._index = TweetIdIndex.build(self._root)
        return self._index

    async def batch_check_exists(self, tweet_ids: list[str]) -> set[str]:
        if not tweet_ids:
            return set()
        return self._idx.filter_existing(tweet_ids)

    async def tweet_exists(self, tweet_id: str) -> bool:
        return self._idx.contains(tweet_id)

    async def save_tweets(self, tweets: list[Tweet], early_stop_threshold: int = 5) -> SaveResult:
        if not tweets:
            return SaveResult(success_count=0, skipped_count=0, error_count=0)

        existing = await self.batch_check_exists([t.tweet_id for t in tweets])
        success = skipped = error = 0
        consecutive = 0
        saved_ids: list[str] = []
        to_write: list[Tweet] = []
        seen_in_batch: set[str] = set()

        for tweet in tweets:
            if tweet.tweet_id in existing or tweet.tweet_id in seen_in_batch:
                skipped += 1
                consecutive += 1
                if early_stop_threshold > 0 and consecutive >= early_stop_threshold:
                    remaining = len(tweets) - success - skipped
                    skipped += remaining
                    break
                continue
            consecutive = 0
            seen_in_batch.add(tweet.tweet_id)
            to_write.append(tweet)
            saved_ids.append(tweet.tweet_id)
            success += 1

        groups: dict[Path, list[dict[str, Any]]] = {}
        written: list[dict[str, Any]] = []
        for tw in to_write:
            rec = _to_record(tw)
            written.append(rec)
            shard = paths.canonical_shard(self._root, tw.author_username, tw.created_at)
            groups.setdefault(shard, []).append(rec)
        for shard, recs in groups.items():
            async with shard_lock(shard):
                upsert(shard, recs, key="tweet_id")
        # canonical 写成功 = 提交点;随后增量更新受影响 by-day 派生视图
        if written:
            await views.by_day_upsert(self._root, written)

        for tid in saved_ids:
            self._idx.add(tid)

        return SaveResult(
            success_count=success, skipped_count=skipped,
            error_count=error, saved_tweet_ids=saved_ids,
        )

    async def get_tweets_by_author(self, author_username: str, limit: int = 100) -> list[Tweet]:
        wanted = author_username.lower()
        records: list[dict[str, Any]] = []
        for shard in paths.author_shards(self._root, author_username):
            records.extend(read_shard(shard))
        records = [r for r in records if r.get("author_username", "").lower() == wanted]
        records.sort(key=_parse, reverse=True)
        limit = max(limit, 0)
        return [_to_domain(r) for r in records[:limit]]

    async def get_by_day(self, local_date: date, tz_offset_min: int, *,
                         min_text_length: int = 0, limit: int | None = None) -> list[Tweet]:
        utc_start, utc_end = paths.local_day_to_utc_window(local_date, tz_offset_min)
        utc_dates = paths.utc_dates_in_window(utc_start, utc_end)
        records = views.read_by_day_dates(self._root, utc_dates)
        matched = [
            r for r in records
            if utc_start <= _parse(r) < utc_end and len(r.get("text", "")) >= min_text_length
        ]
        matched.sort(key=_parse)  # ASC 正序(逐方法照抄旧 browse get_tweets)
        if limit is not None:
            matched = matched[:max(limit, 0)]
        return [_to_domain(r) for r in matched]

    async def get_by_author_range(self, author_username: str, since: datetime, until: datetime, *,
                                  min_text_length: int = 0, page: int = 1, page_size: int = 50) -> Page[Tweet]:
        since, until = paths.as_utc(since), paths.as_utc(until)
        wanted = author_username.lower()
        records: list[dict[str, Any]] = []
        for shard in paths.author_shards(self._root, author_username):
            records.extend(read_shard(shard))
        matched = [
            r for r in records
            if r.get("author_username", "").lower() == wanted
            and since <= _parse(r) < until and len(r.get("text", "")) >= min_text_length
        ]
        total = len(matched)
        matched.sort(key=_parse, reverse=True)  # DESC 倒序
        offset = (page - 1) * page_size
        items = [_to_domain(r) for r in matched[offset:offset + page_size]]
        total_pages = math.ceil(total / page_size) if total > 0 and page_size > 0 else 0
        return Page[Tweet](items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)

    async def get_feed(self, since: datetime, until: datetime | None = None, *,
                       limit: int = 50) -> Feed[Tweet]:
        since = paths.as_utc(since)
        until_eff = paths.as_utc(until) if until is not None else datetime(9999, 12, 31, tzinfo=UTC)
        records = views.read_by_day_range(self._root, since, until_eff)
        matched = [r for r in records if since <= _parse(r) < until_eff]
        total = len(matched)
        matched.sort(key=_parse, reverse=True)  # DESC 倒序
        items = [_to_domain(r) for r in matched[:max(limit, 0)]]
        count = len(items)
        return Feed[Tweet](items=items, count=count, total=total, has_more=count < total)

    async def get_all_tweets(self) -> list[Tweet]:
        """枚举全部 canonical 分片的推文(无序;Export 全量读,调用方再过滤/对账靠 normalize 排序)。"""
        records: list[dict[str, Any]] = []
        for shard in paths.iter_canonical_shards(self._root):
            records.extend(read_shard(shard))
        return [_to_domain(r) for r in records]

    async def upsert_tweets(self, records: list[dict[str, Any]]) -> None:
        """按 tweet_id 插入或全字段覆盖(import 写底座;records=导出格式 12 字段,直调
        jsonl upsert 无 skip)。⚠️ 仅写命中 author/月分片:fixtures overwrite 须保持
        author_username+created_at 稳定(同分片),否则旧分片残留致 get_all_tweets 重复。"""
        if not records:
            return
        groups: dict[Path, list[dict[str, Any]]] = {}
        for rec in records:
            created = datetime.fromisoformat(rec["created_at"])
            shard = paths.canonical_shard(self._root, rec["author_username"], created)
            groups.setdefault(shard, []).append(rec)
        for shard, recs in groups.items():
            async with shard_lock(shard):
                upsert(shard, recs, key="tweet_id")
        await views.by_day_upsert(self._root, records)
        for rec in records:
            self._idx.add(rec["tweet_id"])
