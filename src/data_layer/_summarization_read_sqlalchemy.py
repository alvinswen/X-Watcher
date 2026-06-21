"""sqlalchemy 适配器:逐字复刻 summarization_tools 当前两条 raw 查询,产与文件层同构 dict
(get_unsummarized_tweets 8 字段 list[dict];get_tweet_origins dict keyed by tweet_id)。
created_at 经 _dt_to_iso 与文件层同形态(aware→...+00:00),保证默认模式工具 JSON 输出不变。"""
from __future__ import annotations

from datetime import timezone

from sqlalchemy import select

from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm


def _dt_to_iso(dt):
    if dt is None:
        return None
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.isoformat()


class SqlalchemySummarizationReadStore:
    def __init__(self, session):
        self._session = session

    async def get_unsummarized_tweets(self, since=None, until=None, author=None, limit=50):
        clamped = min(max(limit, 1), 200)
        stmt = (
            select(
                TweetOrm.tweet_id,
                TweetOrm.text,
                TweetOrm.author_username,
                TweetOrm.author_display_name,
                TweetOrm.reference_type,
                TweetOrm.referenced_tweet_text,
                TweetOrm.referenced_tweet_author_username,
                TweetOrm.created_at,
            )
            .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
            .where(SummaryOrm.summary_id == None)  # noqa: E711
        )
        if since:
            stmt = stmt.where(TweetOrm.created_at >= since)
        if until:
            stmt = stmt.where(TweetOrm.created_at < until)
        if author:
            stmt = stmt.where(TweetOrm.author_username == author)
        stmt = stmt.order_by(TweetOrm.created_at.desc()).limit(clamped)
        rows = (await self._session.execute(stmt)).fetchall()
        return [
            {
                "tweet_id": r._mapping["tweet_id"],
                "text": r._mapping["text"],
                "author_username": r._mapping["author_username"],
                "author_display_name": r._mapping["author_display_name"],
                "reference_type": r._mapping["reference_type"],
                "referenced_tweet_text": r._mapping["referenced_tweet_text"],
                "referenced_tweet_author_username": r._mapping["referenced_tweet_author_username"],
                "created_at": _dt_to_iso(r._mapping["created_at"]),
            }
            for r in rows
        ]

    async def get_tweet_origins(self, tweet_ids):
        if not tweet_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    TweetOrm.tweet_id,
                    TweetOrm.text,
                    TweetOrm.referenced_tweet_text,
                    TweetOrm.reference_type,
                ).where(TweetOrm.tweet_id.in_(tweet_ids))
            )
        ).fetchall()
        return {
            r._mapping["tweet_id"]: {
                "text": r._mapping["text"],
                "referenced_tweet_text": r._mapping["referenced_tweet_text"],
                "reference_type": r._mapping["reference_type"],
            }
            for r in rows
        }
