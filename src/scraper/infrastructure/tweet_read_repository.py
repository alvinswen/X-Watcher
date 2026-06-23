"""旧应用自有 tweet 读门面:复刻 `src/api/routes/tweets.py` 两 HTTP 端点裸查 ORM。

- list_tweets:GET /api/tweets。原 SQL = select(TweetOrm 字段...) LEFT JOIN SummaryOrm
  (CASE has_summary) + _apply_filters(author 大小写不敏感 / created_after >= / created_before <)
  + 单独 count(同 filter,无 join) + order_by created_at DESC + offset/limit。
- get_tweet_detail:GET /api/tweets/{id}。原 SQL = select(TweetOrm 字段...) where tweet_id==。

file 模式不依赖 ORM,组合既有 file store(FileTweetStore + FileSummaryStore)在 Python 槽内
过滤/JOIN/排序/分页;sqlalchemy 模式逐字复刻原 SQL,保证默认模式响应字节零变化。

⚠️ db_created_at 降级(owner 已定 emit created_at):文件层 Tweet domain **无 db_created_at**
  (DB 管理列未持久化)。file 模式 db_created_at **返回该推文的 created_at**(降级,同 2b'
  profiles updated_at→fetched_at)。sqlalchemy 模式返真实 TweetOrm.db_created_at(零行为变化)。

⚠️ created_at 不在门面归一:响应模型 TweetListItem(UTCDatetimeModel)序列化时把 naive(pg)和
  aware-UTC(file)都归一为 "...+00:00",两模式 JSON 一致。门面按 domain/ORM 原样返回(file
  aware / sqlalchemy naive),不 strip tzinfo。

⚠️ reference_type:列表项是字符串。file domain 是 enum → 返 .value;sqlalchemy 返裸 ORM 字符串列。

parity 要点:
- total 一致:file count 与 sqlalchemy count 对同 filter 必须相等(均按 tweet 计数,不受 summary
  fan-out 影响)。
- has_summary:有 summary 的 tweet → True。
- 分页 tie-order:同 created_at 在 page 边界,file(确定性 tie-break:created_at DESC 后按
  tweet_id DESC)vs PG(引擎任意)可能取不同子集。跨模式对账测试用互异 created_at 规避(同
  browse-agg tie-order 限制)。
- ⚠️ list 的 outerjoin fan-out:schema 上 summaries.tweet_id 无 unique 约束,一个 tweet 可能有
  多条 summary;原 list SQL 的 outerjoin 会 fan-out(每条 summary 一行 item),但 count 单独算
  (无 join)→ 一个多 summary 的 tweet 在 items 里出现多次、total 只计一次。两侧门面忠实复刻该
  行为(file 对每条 tweet 按其 summary 数产行);跨模式对账测试用 1:≤1 summary 规避 fan-out。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


class FileTweetReadStore:
    """组合 FileTweetStore + FileSummaryStore 的 file 模式 tweet 读门面。"""

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    def _item(self, tw, has_summary: bool) -> dict:
        media = (
            [m.model_dump(mode="json", exclude_none=True) for m in tw.media]
            if tw.media
            else None
        )
        return {
            "tweet_id": tw.tweet_id,
            "text": tw.text,
            "author_username": tw.author_username,
            "author_display_name": tw.author_display_name,
            "created_at": tw.created_at,          # aware +00:00;序列化层归一,不 strip
            "db_created_at": tw.created_at,        # ⚠️ 降级:文件层无 DB 入库时间 → 返 created_at
            "reference_type": tw.reference_type.value if tw.reference_type else None,
            "referenced_tweet_id": tw.referenced_tweet_id,
            "media": media,
            "has_summary": has_summary,
            "media_count": len(media) if media else 0,
        }

    async def _summary_tweet_ids(self) -> set[str]:
        # ⚠️ 全量加载摘要建集合复刻 LEFT JOIN has_summary(perf 弱点 deferred,承 feed/search 范式)
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        recs = await FileSummaryStore(self._root).get_all_summaries()
        return {r.tweet_id for r in recs}

    async def list_tweets(
        self,
        *,
        page: int,
        page_size: int,
        author: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> tuple[list[dict], int]:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        tweets = await FileTweetStore(self._root).get_all_tweets()

        # _apply_filters 复刻:author 大小写不敏感 == / created_after >= / created_before <
        if author:
            wanted = author.lower()
            tweets = [t for t in tweets if t.author_username.lower() == wanted]
        if created_after is not None:
            tweets = [t for t in tweets if t.created_at >= created_after]
        if created_before is not None:
            tweets = [t for t in tweets if t.created_at < created_before]

        # total:按 tweet 计数(不受 summary fan-out 影响,对齐 count select_from(TweetOrm))
        total = len(tweets)

        # has_summary 集合(列表 outerjoin CASE)
        summary_ids = await self._summary_tweet_ids()

        # order_by created_at DESC;同 created_at 确定性 tie-break(tweet_id DESC),规避 PG 任意序
        tweets.sort(key=lambda t: (t.created_at, t.tweet_id), reverse=True)

        offset = (page - 1) * page_size
        page_tweets = tweets[offset : offset + page_size]
        items = [
            self._item(t, has_summary=t.tweet_id in summary_ids) for t in page_tweets
        ]
        return items, total

    async def get_tweet_detail(self, tweet_id: str) -> dict | None:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        tweets = await FileTweetStore(self._root).get_all_tweets()
        match = next((t for t in tweets if t.tweet_id == tweet_id), None)
        if match is None:
            return None
        # detail 主查询不算 has_summary(handler 默认 False,summary 部分另走 get_summary_repo)
        return self._item(match, has_summary=False)


class SqlalchemyTweetReadStore:
    """sqlalchemy 模式:逐字复刻两端点原 SQL,默认模式响应字节零变化。"""

    def __init__(self, session) -> None:
        self._session = session

    @staticmethod
    def _apply_filters(stmt, *, author, created_after, created_before):
        from sqlalchemy import func

        from src.scraper.infrastructure.models import TweetOrm

        if author:
            stmt = stmt.where(func.lower(TweetOrm.author_username) == author.lower())
        if created_after is not None:
            stmt = stmt.where(TweetOrm.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(TweetOrm.created_at < created_before)
        return stmt

    async def list_tweets(
        self,
        *,
        page: int,
        page_size: int,
        author: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> tuple[list[dict], int]:
        from sqlalchemy import case, func, select

        from src.scraper.infrastructure.models import TweetOrm
        from src.summarization.infrastructure.models import SummaryOrm

        stmt = select(
            TweetOrm.tweet_id,
            TweetOrm.text,
            TweetOrm.created_at,
            TweetOrm.author_username,
            TweetOrm.author_display_name,
            TweetOrm.referenced_tweet_id,
            TweetOrm.reference_type,
            TweetOrm.media,
            TweetOrm.db_created_at,
            TweetOrm.db_updated_at,
            case((SummaryOrm.summary_id.isnot(None), True), else_=False).label(
                "has_summary"
            ),
        ).outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)

        stmt = self._apply_filters(
            stmt, author=author, created_after=created_after, created_before=created_before
        )

        count_stmt = select(func.count()).select_from(TweetOrm)
        count_stmt = self._apply_filters(
            count_stmt,
            author=author,
            created_after=created_after,
            created_before=created_before,
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = stmt.order_by(TweetOrm.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        items = []
        for row in rows:
            d = dict(row._mapping)
            media = d.get("media")
            items.append(
                {
                    "tweet_id": d["tweet_id"],
                    "text": d["text"],
                    "author_username": d["author_username"],
                    "author_display_name": d.get("author_display_name"),
                    "created_at": d["created_at"],
                    "db_created_at": d["db_created_at"],
                    "reference_type": d.get("reference_type"),
                    "referenced_tweet_id": d.get("referenced_tweet_id"),
                    "media": media,
                    "has_summary": bool(d.get("has_summary", False)),
                    "media_count": len(media) if media else 0,
                }
            )
        return items, total

    async def get_tweet_detail(self, tweet_id: str) -> dict | None:
        from sqlalchemy import select

        from src.scraper.infrastructure.models import TweetOrm

        stmt = select(
            TweetOrm.tweet_id,
            TweetOrm.text,
            TweetOrm.created_at,
            TweetOrm.db_created_at,
            TweetOrm.author_username,
            TweetOrm.author_display_name,
            TweetOrm.referenced_tweet_id,
            TweetOrm.reference_type,
            TweetOrm.media,
        ).where(TweetOrm.tweet_id == tweet_id)

        result = await self._session.execute(stmt)
        row = result.first()
        if row is None:
            return None

        media = row.media
        return {
            "tweet_id": row.tweet_id,
            "text": row.text,
            "author_username": row.author_username,
            "author_display_name": row.author_display_name,
            "created_at": row.created_at,
            "db_created_at": row.db_created_at,
            "reference_type": row.reference_type,
            "referenced_tweet_id": row.referenced_tweet_id,
            "media": media,
            "has_summary": False,
            "media_count": len(media) if media else 0,
        }
