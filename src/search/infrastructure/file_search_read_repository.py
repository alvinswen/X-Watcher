"""文件版 search 读门面:search_tweets(多词 AND + 时间窗/author + tweet↔summary JOIN)。

组合 FileTweetStore(窗口快路径 get_feed[since 提供] / 全扫 get_all_tweets[since 无])+
FileSummaryStore.get_all_summaries(全量摘要建 map 左连接)。复刻旧 SearchService.search_tweets
形态(14 字段 item,DESC + offset 分页)。
- keyword:复用 src.shared.like_match.ilike_contains 复刻 PG ILIKE(LIKE 通配 + 非 ASCII case-fold 对齐 PG)。
- db_created_at:文件层无 DB 入库时间 → None(同 feed;sqlalchemy 模式仍真值)。
- created_at aware(+00:00)/ media exclude_none(承 browse/feed)。
- perf:无 since → get_all_tweets 全扫(~1.6s deferred);有 since → by-day 窗口快路径。
"""
from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

from src.search.api.schemas import SearchResult
from src.shared.like_match import ilike_contains

_NO_LIMIT = 10**12  # FileTweetStore.get_feed 无 unlimited 参;大 limit 取窗口内全部


class FileSearchReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def _build_summary_map(self) -> dict[str, Any]:
        from src.shared.read_cache import load_summary_map
        return await load_summary_map(self._root)

    async def _candidates(self, since: Any, until: Any) -> list[Any]:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        store = FileTweetStore(self._root)
        if since is not None:
            # 窗口快路径:by-day 视图取 [since, until)(until=None → [since, ∞))
            return (await store.get_feed(since, until, limit=_NO_LIMIT)).items
        # since 无:全扫兜底 + until 过滤(created_at < until)
        tweets = await store.get_all_tweets()
        if until is not None:
            until_cmp = until if until.tzinfo is not None else until.replace(tzinfo=UTC)
            tweets = [t for t in tweets if t.created_at < until_cmp]
        return tweets

    @staticmethod
    def _item(tw: Any, rec: Any) -> dict[str, Any]:
        return {
            "tweet_id": tw.tweet_id,
            "text": tw.text,
            "author_username": tw.author_username,
            "author_display_name": tw.author_display_name,
            "created_at": tw.created_at,        # aware +00:00,匹配生产 pg
            "db_created_at": None,              # 文件层无入库时间(同 feed)
            "reference_type": tw.reference_type.value if tw.reference_type else None,
            "referenced_tweet_id": tw.referenced_tweet_id,
            "referenced_tweet_text": tw.referenced_tweet_text,
            "referenced_tweet_author_username": tw.referenced_tweet_author_username,
            "media": [m.model_dump(mode="json", exclude_none=True) for m in tw.media] if tw.media else None,
            "referenced_tweet_media": (
                [m.model_dump(mode="json", exclude_none=True) for m in tw.referenced_tweet_media]
                if tw.referenced_tweet_media else None
            ),
            "summary_text": rec.summary_text if rec else None,
            "translation_text": rec.translation_text if rec else None,
        }

    async def search_tweets(self, q: Any, page: Any = 1, page_size: Any = 20, include_summary: Any = True,
                            author: Any = None, authors: Any = None, since: Any = None, until: Any = None) -> SearchResult:
        keywords = q.split()
        tweets = await self._candidates(since, until)
        # author/authors 过滤(互斥,author 优先,镜像 oracle)
        if author:
            wanted = author.lower()
            tweets = [t for t in tweets if t.author_username.lower() == wanted]
        elif authors:
            wanted_set = {a.lower() for a in authors}
            tweets = [t for t in tweets if t.author_username.lower() in wanted_set]
        # summary map(include_summary 时;keyword over summary + item 填充都需)
        smap = await self._build_summary_map() if include_summary else {}
        # 多词 AND:每词命中 text/ref(+summary/translation if include_summary)至少一字段
        if keywords:
            def _match_kw(t: Any, kw: Any) -> bool:
                if ilike_contains(t.text, kw) or ilike_contains(t.referenced_tweet_text, kw):
                    return True
                if include_summary:
                    rec = smap.get(t.tweet_id)
                    if rec and (ilike_contains(rec.summary_text, kw)
                                or ilike_contains(rec.translation_text, kw)):
                        return True
                return False
            tweets = [t for t in tweets if all(_match_kw(t, kw) for kw in keywords)]
        # COUNT 过滤后 + DESC(统一排序,兜底全扫无序)+ offset 分页
        total = len(tweets)
        tweets_sorted = sorted(tweets, key=lambda t: t.created_at, reverse=True)
        offset = (page - 1) * page_size
        page_tweets = tweets_sorted[offset:offset + page_size]
        items = [self._item(t, smap.get(t.tweet_id) if include_summary else None) for t in page_tweets]
        return SearchResult(items=items, total=total)
