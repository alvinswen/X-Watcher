# src/sync/infrastructure/file_import_repository.py
"""文件版 Import 门面:import_* 重写策略分支(insert/skip/overwrite-by-key/merge)。

- seed_*/export_* 委派 FileExportStore(read-back 复用 export 片);import 与 seed 共享自有写 store
  实例(tweets 索引一致性)。两侧 import_* 同签名收 list[dict]+strategy(str enum 比较跨类成立)。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.scraper.infrastructure.file_article_repository import FileArticleStore
from src.sync.domain.models import ConflictStrategy, ImportStats
from src.sync.infrastructure.file_export_repository import FileExportStore


def _to_naive(s: Any) -> datetime | None:
    """ISO 串/datetime → naive UTC datetime(逐字对齐 oracle _iso_to_naive_dt:先 astimezone(utc) 再剥 tz)。None→None。"""
    if s is None:
        return None
    dt = datetime.fromisoformat(s) if isinstance(s, str) else s
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _naive_str(v: Any) -> str | None:
    """aware ISO 串 → naive ISO 串(剥 tz);None→None。"""
    n = _to_naive(v)
    return n.isoformat() if n is not None else None


# 各实体业务时间戳字段:import 写入须把导出格式的 aware("+00:00")串归一为 naive 串,
# 对齐 oracle dict_to_*(_iso_to_naive_dt)+ 文件世界 naive 约定(seed/create 存 naive)。
# 否则 import 的 aware 串与 seed 的 naive 串混存,会令 get_all_follows 等按 domain datetime
# 排序时 "naive vs aware 不可比" 崩溃(实测 FOL 混合案)。
_DT_FIELDS = {
    "follows": ("added_at", "backfill_completed_at"),
    "tweets": ("created_at",),
    "summaries": ("created_at",),
    "articles": ("fetched_at",),
}


def _naive_item(item: Any, kind: Any) -> dict[str, Any]:
    """返回 item 副本:把该实体的 datetime 字段转 naive ISO 串(对齐 oracle/文件世界 naive 约定)。"""
    return {**item, **{f: _naive_str(item.get(f)) for f in _DT_FIELDS[kind] if f in item}}


class FileImportStore:
    def __init__(self, data_root: Path) -> None:
        root = Path(data_root)
        self._root = root
        self._follows = FileFollowStore(root)
        self._tweets = FileTweetStore(root)
        self._summaries = FileSummaryStore(root)
        self._articles = FileArticleStore(root)

    # ── seed(初态,委派 FileExportStore 同款,两侧 case 共用)──
    async def seed_follows(self, follows: Any) -> None:
        await self._follows.seed(follows)

    async def seed_tweets(self, tweets: Any) -> None:
        await self._tweets.save_tweets(tweets, early_stop_threshold=0)

    async def seed_summaries(self, records: Any) -> None:
        await self._summaries.seed(records)

    async def seed_articles(self, articles: Any) -> None:
        await self._articles.seed(articles)

    # ── export(read-back,委派 FileExportStore 新建实例:扫盘,索引/视图无关)──
    async def export_follows(self) -> list[dict[str, Any]]:
        return await FileExportStore(self._root).export_follows()

    async def export_tweets(
        self, since: Any = None, until: Any = None, authors: Any = None
    ) -> list[dict[str, Any]]:
        return await FileExportStore(self._root).export_tweets(since, until, authors)

    async def export_summaries(self, tweet_ids: Any = None) -> list[dict[str, Any]]:
        return await FileExportStore(self._root).export_summaries(tweet_ids)

    async def export_articles(self, tweet_ids: Any = None) -> list[dict[str, Any]]:
        return await FileExportStore(self._root).export_articles(tweet_ids)

    # ── import(策略分支,逐字镜像 oracle ImportRepository 语义)──
    async def import_follows(self, items: Any, strategy: Any) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "follows")  # 存 naive 串(对齐 oracle/文件世界,避混存崩排序)
            existing = await self._follows.get_follow_by_username(item["username"])
            if existing is None:
                await self._follows.upsert_follow(item)
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._follows.upsert_follow(item)
                stats.updated += 1
            elif strategy == ConflictStrategy.merge:
                imp = _to_naive(item.get("added_at"))
                cur = _to_naive(existing.added_at)
                if imp and cur and imp > cur:
                    await self._follows.upsert_follow(item)
                    stats.updated += 1
                else:
                    stats.skipped += 1
        return stats

    async def import_tweets(self, items: Any, strategy: Any) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "tweets")
            if not await self._tweets.tweet_exists(item["tweet_id"]):
                await self._tweets.upsert_tweets([item])
                stats.inserted += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._tweets.upsert_tweets([item])
                stats.updated += 1
        return stats

    async def import_summaries(self, items: Any, strategy: Any) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "summaries")
            if not await self._summaries.summary_exists(item["summary_id"]):
                await self._summaries.upsert_summary(item)
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._summaries.upsert_summary(item)
                stats.updated += 1
        return stats

    async def import_articles(self, items: Any, strategy: Any) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "articles")
            if await self._articles.get_article(item["tweet_id"]) is None:
                await self._articles.overwrite_article(item)
                stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._articles.overwrite_article(item)
                stats.updated += 1
        return stats
