"""文件版 browse 读门面:get_tweets / get_author_timeline(含 tweet↔summary 批量 JOIN)。

组合 FileTweetStore(窗口取推文)+ FileSummaryStore(全量摘要建 map 左连接)+ FollowStore(reason)。
复刻旧 BrowseService 的 2 列表方法形态(13 字段 item dict);不做聚合两法(deferred)。

⚠️ created_at 保 aware(+00:00):实测生产 pg(timestamptz)返 aware、data_migrated 存
"...+00:00"、文件层 _to_domain 回读 aware → file 与生产 pg 一致(MCP 路径 isoformat 均出
"+00:00")。**不可归一到 naive 去迎合 SQLite 测试**(SQLite 回读 DateTime(tz) 为 naive
是测试 oracle 工件,非生产语义——同 A1-1 SQLite-vs-PG 陷阱)。跨模式对账对 created_at 按
instant 比对 + 单独钉 file 为 aware "+00:00"。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

_NO_LIMIT = 10**12  # FileTweetStore.get_feed 无 unlimited 参;大 limit 取窗口内全部(复用 feed 范式)


class FileBrowseReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def _build_summary_map(self) -> dict:
        # ⚠️ 全量加载摘要(perf 弱点,deferred 优化),建 {tweet_id: record} 复刻 LEFT JOIN
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
        recs = await FileSummaryStore(self._root).get_all_summaries()
        return {r.tweet_id: r for r in recs}

    @staticmethod
    def _item(tw, rec) -> dict:
        return {
            "tweet_id": tw.tweet_id, "created_at": tw.created_at,   # aware +00:00,匹配生产 pg
            "author_username": tw.author_username, "author_display_name": tw.author_display_name,
            "summary_text": rec.summary_text if rec else None,
            "translation_text": rec.translation_text if rec else None,
            "text": tw.text,
            "reference_type": tw.reference_type.value if tw.reference_type else None,
            "referenced_tweet_id": tw.referenced_tweet_id,
            "referenced_tweet_text": tw.referenced_tweet_text,
            "referenced_tweet_author_username": tw.referenced_tweet_author_username,
            # exclude_none 匹配生产 pg:TweetOrm.from_domain 以 exclude_none 持久化 media,
            # 旧 BrowseService 返存储 JSON(省略 None 键)。不加会多出 preview_image_url/alt_text:null 偏离 pg。
            "media": [m.model_dump(mode="json", exclude_none=True) for m in tw.media] if tw.media else None,
            "referenced_tweet_media": (
                [m.model_dump(mode="json", exclude_none=True) for m in tw.referenced_tweet_media]
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

    async def get_daily_stats(self, year, month, tz_offset=0, min_text_length=None):
        """按用户本地时区分组的每日推文数量。复刻 BrowseService.get_daily_stats:
        月窗 UTC 算术 + get_feed 窗口读 + 按本地日分组计数(date cast=截断,无 round 陷阱)。"""
        from collections import Counter
        from datetime import datetime, timedelta, timezone
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        local_start = datetime(year, month, 1)
        local_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        utc_start = (local_start + timedelta(minutes=tz_offset)).replace(tzinfo=timezone.utc)
        utc_end = (local_end + timedelta(minutes=tz_offset)).replace(tzinfo=timezone.utc)

        feed = await FileTweetStore(self._root).get_feed(utc_start, utc_end, limit=_NO_LIMIT)
        min_len = min_text_length or 0
        counter: Counter = Counter()
        for tw in feed.items:
            if len(tw.text or "") < min_len:
                continue
            created = tw.created_at if tw.created_at.tzinfo else tw.created_at.replace(tzinfo=timezone.utc)
            # 复刻 sql_date_with_offset(col, -tz_offset)::DATE:local=UTC+(-tz_offset)分,取日(截断)
            local_date = (created + timedelta(minutes=-tz_offset)).date()
            counter[local_date.isoformat()] += 1
        return [{"date": d, "count": counter[d]} for d in sorted(counter)]

    async def get_authors(self, date, tz_offset=0, min_text_length=None):
        """指定本地日有推文的作者列表(count+max+display_name+reason),按 max DESC。
        复刻 BrowseService.get_authors:精确 author_username 分组 + 大小写不敏感最新 display_name
        + 精确 username reason 匹配(active follow)。COUNT/MAX 无除法,无 round 陷阱。"""
        from datetime import datetime
        from src.data_layer.provider import get_follows_repo
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        local_date = datetime.strptime(date, "%Y-%m-%d").date()
        tweets = await FileTweetStore(self._root).get_by_day(
            local_date, tz_offset, min_text_length=min_text_length or 0, limit=None
        )
        groups: dict = {}             # 精确 username -> {"count", "max"}
        latest_by_lower: dict = {}    # lower(username) -> (max_created, display_name)
        for tw in tweets:
            g = groups.get(tw.author_username)
            if g is None:
                groups[tw.author_username] = g = {"count": 0, "max": tw.created_at}
            g["count"] += 1
            if tw.created_at > g["max"]:
                g["max"] = tw.created_at
            lu = tw.author_username.lower()
            cur = latest_by_lower.get(lu)
            if cur is None or tw.created_at > cur[0]:
                latest_by_lower[lu] = (tw.created_at, tw.author_display_name)
        # max DESC(Python 稳定排序:tie 保 groups 首现作者序;旧 SQL 无次级 tie-break=PG 未定义序,承 A1-2 caveat)
        ordered = sorted(groups.items(), key=lambda kv: kv[1]["max"], reverse=True)
        # reason:active follow 精确 username 匹配(复刻 ScraperFollow.username.in_(usernames)+is_active)
        active = await get_follows_repo(None).get_active_follows()
        reason_map = {f.username: f.reason for f in active}
        return [{
            "author_username": username,
            "author_display_name": latest_by_lower[username.lower()][1],
            "tweet_count": g["count"],
            "last_tweet_at": g["max"],
            "reason": reason_map.get(username),
        } for username, g in ordered]
