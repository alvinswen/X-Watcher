"""文件版 topic 跨域读门面:复刻 `_query_tweets`(TweetOrm LEFT JOIN SummaryOrm)。

复刻 `src/topic/services/topic_summary_service.py` 的 `_query_tweets` 内联直查 ORM 的那段
聚合查询(取指定账号在时间窗内的推文,outerjoin 已有翻译),file 模式下不依赖 ORM,改
组合既有 file store(FileTweetStore + FileSummaryStore)在 Python 槽内做过滤/outerjoin/排序。

语义(逐条复刻原 SQL):
- 作者名**大小写不敏感**:func.lower(author).in_([u.lower() for u in usernames])。
- 时间窗**闭区间**:created_at >= start_time AND created_at <= end_time(两端都含,end 是 <=)。
- outerjoin SummaryOrm 取 translation_text:无 summary 的 tweet → translation=None。
- 排序:created_at ASC。
- 返回 dict 键:tweet_id, text, author, created_at, translation,
  referenced_tweet_text, referenced_tweet_author_username。

⚠️⚠️ created_at 必须返回 **naive-UTC 裸 datetime**(不是 iso 串):
  原 pg 路径返回 naive datetime(str()="2026-02-18 03:30:00",无时区);file domain 读回是
  aware-UTC(str()="...+00:00")。下游 _build_prompt 用 str(created_at) 插值进 prompt 文本、
  并用它跨域排序(混 aware/naive 会 crash)。门面把 created_at 经 _naive_utc 归一为 naive-UTC,
  与 pg naive 形态字节一致。sqlalchemy 门面逐字复刻原 SQL(直接返回 row[3] 即 pg naive),天然一致。

⚠️ outerjoin 多重性:schema 上 summaries.tweet_id **无 unique 约束**,一个 tweet 可能有多条
  summary;原 SQL 用 result.all()(非 scalar_one_or_none)会 fan-out 多行(每条 summary 一行)。
  file 门面忠实复刻:对每条 tweet,按其 summary 列表逐条产行(无 summary → 单行 translation=None)。
  同 created_at 时多 summary 行间的 tie-order 是已知限制(file=summary 插入序;真实数据 1 tweet
  多 summary 罕见,跨模式对账测试用 1:≤1 严格逐 dict 相等)。

⚠️ 无 round 陷阱豁免:本片是过滤/outerjoin/排序,无除法分桶,SQLite 是有效 oracle。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _naive_utc(dt: datetime) -> datetime:
    """归一到 naive-UTC 裸 datetime:naive 当作 UTC,aware→astimezone UTC,再去 tzinfo。"""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _in_window(ts: datetime, lo: datetime, hi: datetime) -> bool:
    """闭区间判定:lo <= ts <= hi(end 用 <=,非半开)。三者均已归一同时区意识。"""
    return lo <= ts <= hi


class FileTopicQueryStore:
    """组合 FileTweetStore + FileSummaryStore 的 file 模式跨域读门面。"""

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def query_tweets(
        self, usernames: list[str], start_time: datetime, end_time: datetime
    ) -> list[dict]:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        wanted = {u.lower() for u in usernames}
        # 时间比较:start/end 也归一到 naive-UTC,避免 aware vs naive 比较 crash
        lo = _naive_utc(start_time)
        hi = _naive_utc(end_time)

        # tweet_id → [translation_text, ...](outerjoin fan-out:多 summary 多行)
        summaries = await FileSummaryStore(self._root).get_all_summaries()
        translations_by_tweet: dict[str, list[str | None]] = {}
        for s in summaries:
            translations_by_tweet.setdefault(s.tweet_id, []).append(s.translation_text)

        # 作者(大小写不敏感)+ 闭区间时间窗过滤
        tweets = await FileTweetStore(self._root).get_all_tweets()
        matched = [
            t for t in tweets
            if t.author_username.lower() in wanted
            and _in_window(_naive_utc(t.created_at), lo, hi)
        ]
        # 排序 created_at ASC(naive-UTC 归一后比较,稳定)
        matched.sort(key=lambda t: _naive_utc(t.created_at))

        rows: list[dict] = []
        for t in matched:
            translations = translations_by_tweet.get(t.tweet_id)
            # outerjoin:无 summary → 单行 None;有 N 条 summary → N 行(各带 translation)
            for translation in (translations if translations else [None]):
                rows.append({
                    "tweet_id": t.tweet_id,
                    "text": t.text,
                    "author": t.author_username,
                    "created_at": _naive_utc(t.created_at),
                    "translation": translation,
                    "referenced_tweet_text": t.referenced_tweet_text,
                    "referenced_tweet_author_username": t.referenced_tweet_author_username,
                })
        return rows


class SqlalchemyTopicQueryStore:
    """sqlalchemy 模式:逐字复刻原 _query_tweets 的内联 SQL,SQL 字节零变化。"""

    def __init__(self, session) -> None:
        self._session = session

    async def query_tweets(
        self, usernames: list[str], start_time: datetime, end_time: datetime
    ) -> list[dict]:
        from sqlalchemy import func, select

        from src.scraper.infrastructure.models import TweetOrm
        from src.summarization.infrastructure.models import SummaryOrm

        stmt = (
            select(
                TweetOrm.tweet_id,
                TweetOrm.text,
                TweetOrm.author_username,
                TweetOrm.created_at,
                SummaryOrm.translation_text,
                TweetOrm.referenced_tweet_text,
                TweetOrm.referenced_tweet_author_username,
            )
            .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
            .where(
                func.lower(TweetOrm.author_username).in_([u.lower() for u in usernames]),
                TweetOrm.created_at >= start_time,
                TweetOrm.created_at <= end_time,
            )
            .order_by(TweetOrm.created_at.asc())
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        return [
            {
                "tweet_id": row[0],
                "text": row[1],
                "author": row[2],
                "created_at": row[3],
                "translation": row[4],
                "referenced_tweet_text": row[5],
                "referenced_tweet_author_username": row[6],
            }
            for row in rows
        ]
