"""文件版 feed 读门面:get_feed(时间窗增量 + author/keyword 过滤 + tweet↔summary JOIN)。

组合 FileTweetStore.get_feed(窗口取数,复用 A1-2 范式)+ FileSummaryStore.get_all_summaries
(全量摘要建 map 左连接)。复刻旧 FeedService.get_feed 形态(11 字段 item dict,DESC + limit 游标)。
- db_created_at:文件层无 DB 入库时间 → None(spec §3.1;sqlalchemy 模式仍填真值不变)。
- created_at:保 aware(+00:00)匹配生产 pg,不归一 naive(承 A1-2,SQLite naive 是测试工件)。
- media:exclude_none 匹配生产 pg from_domain(承 A1-2)。
- keyword:复刻 PG ILIKE(`ilike("%kw%")`)——大小写不敏感 + kw 内 %/_ 作 LIKE 通配(对齐生产 pg,
  非 SQLite;非 ASCII 大小写折叠按 PG,SQLite 不折叠是已知 oracle 陷阱,见 spec §4.1)。
"""
from __future__ import annotations

import re
from pathlib import Path

from src.feed.api.schemas import FeedResult

_NO_LIMIT = 10**12  # FileTweetStore.get_feed 无 unlimited 参;大 limit 取窗口内全部


def _like_to_regex(like_pattern: str) -> str:
    """SQL LIKE pattern → 等价 regex:% → .*,_ → 任意单字符,其余字面 re.escape。oracle 无 ESCAPE 故 \\ 字面。"""
    out = []
    for ch in like_pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _ilike_contains(haystack: str | None, keyword: str) -> bool:
    """复刻 col.ilike(f"%{kw}%"):大小写不敏感 + kw 内 %/_ 作通配。haystack None → 不匹配(LEFT JOIN NULL)。"""
    if haystack is None:
        return False
    pattern = _like_to_regex(f"%{keyword}%")
    return re.search(pattern, haystack, re.IGNORECASE | re.DOTALL) is not None


class FileFeedReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def _build_summary_map(self) -> dict:
        # ⚠️ 全量加载摘要(perf 弱点 deferred,见 spec §7;承 A1-2),建 {tweet_id: record} 复刻 LEFT JOIN
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
        recs = await FileSummaryStore(self._root).get_all_summaries()
        return {r.tweet_id: r for r in recs}

    @staticmethod
    def _item(tw, rec) -> dict:
        return {
            "tweet_id": tw.tweet_id,
            "text": tw.text,
            "author_username": tw.author_username,
            "author_display_name": tw.author_display_name,
            "created_at": tw.created_at,        # aware +00:00,匹配生产 pg
            "db_created_at": None,              # spec §3.1:文件层无入库时间
            "reference_type": tw.reference_type.value if tw.reference_type else None,
            "referenced_tweet_id": tw.referenced_tweet_id,
            "media": [m.model_dump(mode="json", exclude_none=True) for m in tw.media] if tw.media else None,
            "summary_text": rec.summary_text if rec else None,
            "translation_text": rec.translation_text if rec else None,
        }

    async def get_feed(self, since, until, limit, include_summary=True,
                       author=None, authors=None, keyword=None) -> FeedResult:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        # 1. 窗口候选(by-day 视图,已 DESC),复用底座公共方法;大 limit 取窗口内全部
        window = await FileTweetStore(self._root).get_feed(since, until, limit=_NO_LIMIT)
        tweets = window.items
        # 2. author/authors 过滤(互斥,author 优先,镜像 oracle)
        if author:
            wanted = author.lower()
            tweets = [t for t in tweets if t.author_username.lower() == wanted]
        elif authors:
            wanted_set = {a.lower() for a in authors}
            tweets = [t for t in tweets if t.author_username.lower() in wanted_set]
        # 3. summary map(include_summary 时;keyword over summary + item 填充都需)
        smap = await self._build_summary_map() if include_summary else {}
        # 4. keyword 过滤(复刻 ilike %kw%;include_summary 时 OR 搜 summary/translation)
        if keyword:
            def _match(t):
                if _ilike_contains(t.text, keyword):
                    return True
                if include_summary:
                    rec = smap.get(t.tweet_id)
                    if rec and (_ilike_contains(rec.summary_text, keyword)
                                or _ilike_contains(rec.translation_text, keyword)):
                        return True
                return False
            tweets = [t for t in tweets if _match(t)]
        # 5. COUNT(过滤后)+ DESC(get_feed 已排序,过滤保序)+ limit 游标
        total = len(tweets)
        page_tweets = tweets[:max(limit, 0)]
        items = [self._item(t, smap.get(t.tweet_id) if include_summary else None) for t in page_tweets]
        count = len(items)
        return FeedResult(items=items, count=count, total=total, has_more=count < total)
