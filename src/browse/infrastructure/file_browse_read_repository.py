"""文件版 browse 读门面:get_tweets / get_author_timeline(含 tweet↔summary 批量 JOIN)。

组合 FileTweetStore(窗口取推文)+ FileSummaryStore(全量摘要建 map 左连接)+ FollowStore(reason)。
复刻旧 BrowseService 的 2 列表方法形态(13 字段 item dict);不做聚合两法(deferred)。

created_at 形态对齐 oracle:旧 BrowseService 走 SQLite,DateTime(timezone=True) 经 aiosqlite
回读为 naive(UTC 语义);文件层 _to_domain 回读为 aware(+00:00)。二者同一时刻、经
UTCDatetimeModel 序列化等价,但跨模式 dict 级对账要求逐字相等,故 _item 统一归一到 naive-UTC。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class FileBrowseReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def _build_summary_map(self) -> dict:
        # ⚠️ 全量加载摘要(perf 弱点,deferred 优化),建 {tweet_id: record} 复刻 LEFT JOIN
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
        recs = await FileSummaryStore(self._root).get_all_summaries()
        return {r.tweet_id: r for r in recs}

    @staticmethod
    def _naive_utc(dt):
        # oracle(SQLite/aiosqlite)回读 created_at 为 naive-UTC;文件层为 aware-UTC。
        # 归一到 naive-UTC 使跨模式 item dict 逐字相等(同一时刻、API 层 UTCDatetimeModel 等价处理)。
        if dt is not None and dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    @classmethod
    def _item(cls, tw, rec) -> dict:
        return {
            "tweet_id": tw.tweet_id, "created_at": cls._naive_utc(tw.created_at),
            "author_username": tw.author_username, "author_display_name": tw.author_display_name,
            "summary_text": rec.summary_text if rec else None,
            "translation_text": rec.translation_text if rec else None,
            "text": tw.text,
            "reference_type": tw.reference_type.value if tw.reference_type else None,
            "referenced_tweet_id": tw.referenced_tweet_id,
            "referenced_tweet_text": tw.referenced_tweet_text,
            "referenced_tweet_author_username": tw.referenced_tweet_author_username,
            "media": [m.model_dump(mode="json") for m in tw.media] if tw.media else None,
            "referenced_tweet_media": (
                [m.model_dump(mode="json") for m in tw.referenced_tweet_media]
                if tw.referenced_tweet_media else None
            ),
        }

    async def get_tweets(self, date, author, page, page_size, tz_offset=0, min_text_length=None):
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        local_date = datetime.strptime(date, "%Y-%m-%d").date()
        tweets = await FileTweetStore(self._root).get_by_day(
            local_date, tz_offset, min_text_length=min_text_length or 0, limit=None
        )
        if author:
            wanted = author.lower()
            tweets = [t for t in tweets if t.author_username.lower() == wanted]
        total = len(tweets)
        offset = (page - 1) * page_size
        page_tweets = tweets[offset:offset + page_size]
        smap = await self._build_summary_map()
        items = [self._item(t, smap.get(t.tweet_id)) for t in page_tweets]
        return items, total

    async def get_author_timeline(self, author, since_utc, until_utc, page, page_size, min_text_length=None):
        from src.data_layer.provider import get_follows_repo
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        page_obj = await FileTweetStore(self._root).get_by_author_range(
            author, since_utc, until_utc, min_text_length=min_text_length or 0,
            page=page, page_size=page_size,
        )
        smap = await self._build_summary_map()
        items = [self._item(t, smap.get(t.tweet_id)) for t in page_obj.items]
        display_name = items[0]["author_display_name"] if items else None
        wanted = author.lower()
        reason = next((f.reason for f in await get_follows_repo(None).get_active_follows()
                       if f.username.lower() == wanted), None)
        author_meta = {"author_username": author, "author_display_name": display_name, "reason": reason}
        return author_meta, items, page_obj.total
