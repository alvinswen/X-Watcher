"""ORM ↔ dict 序列化/反序列化。

为每张可同步表提供 to_dict / from_dict 转换函数。
排除 auto-increment id 和本地时间戳（db_created_at / db_updated_at），保留业务时间戳。
"""

from datetime import datetime, timezone
from typing import Any

# ── 工具函数 ──────────────────────────────────────────────────


def _dt_to_iso(dt: datetime | None) -> str | None:
    """datetime → ISO 8601 字符串。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _iso_to_dt(s: str | None) -> datetime | None:
    """ISO 8601 字符串 → datetime。"""
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso_to_naive_dt(s: str | None) -> datetime | None:
    """ISO 8601 字符串 → naive UTC datetime（用于 TIMESTAMP WITHOUT TIME ZONE 列）。"""
    dt = _iso_to_dt(s)
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── ScraperFollow ─────────────────────────────────────────────


def follow_to_dict(orm) -> dict[str, Any]:
    return {
        "username": orm.username,
        "added_at": _dt_to_iso(orm.added_at),
        "reason": orm.reason,
        "added_by": orm.added_by,
        "is_active": orm.is_active,
        "manual_limit": orm.manual_limit,
        "platform_user_id": orm.platform_user_id,
        "brief_intro": orm.brief_intro,
        "backfill_status": orm.backfill_status,
        "backfill_completed_at": _dt_to_iso(orm.backfill_completed_at),
    }


def dict_to_follow(d: dict[str, Any]) -> dict[str, Any]:
    """dict → ScraperFollow 构造参数。"""
    return {
        "username": d["username"],
        "added_at": _iso_to_naive_dt(d.get("added_at"))
        or datetime.now(timezone.utc).replace(tzinfo=None),
        "reason": d.get("reason", ""),
        "added_by": d.get("added_by", "import"),
        "is_active": d.get("is_active", True),
        "manual_limit": d.get("manual_limit"),
        "platform_user_id": d.get("platform_user_id"),
        "brief_intro": d.get("brief_intro"),
        "backfill_status": d.get("backfill_status", "pending"),
        "backfill_completed_at": _iso_to_naive_dt(d.get("backfill_completed_at")),
    }


# ── TweetOrm ─────────────────────────────────────────────────


def tweet_to_dict(orm) -> dict[str, Any]:
    return {
        "tweet_id": orm.tweet_id,
        "text": orm.text,
        "created_at": _dt_to_iso(orm.created_at),
        "author_username": orm.author_username,
        "author_display_name": orm.author_display_name,
        "author_user_id": orm.author_user_id,
        "referenced_tweet_id": orm.referenced_tweet_id,
        "reference_type": orm.reference_type,
        "media": orm.media,
        "referenced_tweet_text": orm.referenced_tweet_text,
        "referenced_tweet_media": orm.referenced_tweet_media,
        "referenced_tweet_author_username": orm.referenced_tweet_author_username,
    }


def dict_to_tweet(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "tweet_id": d["tweet_id"],
        "text": d["text"],
        "created_at": _iso_to_dt(d["created_at"]),
        "author_username": d["author_username"],
        "author_display_name": d.get("author_display_name"),
        "author_user_id": d.get("author_user_id"),
        "referenced_tweet_id": d.get("referenced_tweet_id"),
        "reference_type": d.get("reference_type"),
        "media": d.get("media"),
        "referenced_tweet_text": d.get("referenced_tweet_text"),
        "referenced_tweet_media": d.get("referenced_tweet_media"),
        "referenced_tweet_author_username": d.get("referenced_tweet_author_username"),
    }


# ── SummaryOrm ────────────────────────────────────────────────


def summary_to_dict(orm) -> dict[str, Any]:
    return {
        "summary_id": orm.summary_id,
        "tweet_id": orm.tweet_id,
        "summary_text": orm.summary_text,
        "translation_text": orm.translation_text,
        "model_provider": orm.model_provider,
        "model_name": orm.model_name,
        "prompt_tokens": orm.prompt_tokens,
        "completion_tokens": orm.completion_tokens,
        "total_tokens": orm.total_tokens,
        "cost_usd": orm.cost_usd,
        "cached": orm.cached,
        "is_generated_summary": orm.is_generated_summary,
        "content_hash": orm.content_hash,
        "created_at": _dt_to_iso(orm.created_at),
    }


def dict_to_summary(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary_id": d["summary_id"],
        "tweet_id": d["tweet_id"],
        "summary_text": d["summary_text"],
        "translation_text": d.get("translation_text"),
        "model_provider": d["model_provider"],
        "model_name": d["model_name"],
        "prompt_tokens": d.get("prompt_tokens", 0),
        "completion_tokens": d.get("completion_tokens", 0),
        "total_tokens": d.get("total_tokens", 0),
        "cost_usd": d.get("cost_usd", 0.0),
        "cached": d.get("cached", False),
        "is_generated_summary": d.get("is_generated_summary", True),
        "content_hash": d["content_hash"],
        "created_at": _iso_to_dt(d.get("created_at")),
    }


# ── ArticleOrm ────────────────────────────────────────────────


def article_to_dict(orm) -> dict[str, Any]:
    return {
        "tweet_id": orm.tweet_id,
        "title": orm.title,
        "preview_text": orm.preview_text,
        "cover_image_url": orm.cover_image_url,
        "content": orm.content,
        "content_html": orm.content_html,
        "author_username": orm.author_username,
        "fetched_at": _dt_to_iso(orm.fetched_at),
    }


def dict_to_article(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "tweet_id": d["tweet_id"],
        "title": d.get("title"),
        "preview_text": d.get("preview_text"),
        "cover_image_url": d.get("cover_image_url"),
        "content": d.get("content"),
        "content_html": d.get("content_html"),
        "author_username": d.get("author_username"),
        "fetched_at": _iso_to_dt(d.get("fetched_at")),
    }
