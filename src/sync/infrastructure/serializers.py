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
        "added_at": _iso_to_dt(d.get("added_at")) or datetime.now(timezone.utc),
        "reason": d.get("reason", ""),
        "added_by": d.get("added_by", "import"),
        "is_active": d.get("is_active", True),
        "manual_limit": d.get("manual_limit"),
        "platform_user_id": d.get("platform_user_id"),
        "brief_intro": d.get("brief_intro"),
        "backfill_status": d.get("backfill_status", "pending"),
        "backfill_completed_at": _iso_to_dt(d.get("backfill_completed_at")),
    }


# ── ScraperScheduleConfig ────────────────────────────────────

def schedule_config_to_dict(orm) -> dict[str, Any]:
    return {
        "interval_seconds": orm.interval_seconds,
        "next_run_time": _dt_to_iso(orm.next_run_time),
        "is_enabled": orm.is_enabled,
        "updated_at": _dt_to_iso(orm.updated_at),
        "updated_by": orm.updated_by,
    }


def dict_to_schedule_config(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "interval_seconds": d.get("interval_seconds", 43200),
        "next_run_time": _iso_to_dt(d.get("next_run_time")),
        "is_enabled": d.get("is_enabled", True),
        "updated_at": _iso_to_dt(d.get("updated_at")) or datetime.now(timezone.utc),
        "updated_by": d.get("updated_by", "import"),
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


# ── Topics（嵌套结构）────────────────────────────────────────

def topic_to_dict(orm) -> dict[str, Any]:
    """将 TopicOrm 及其关联的 accounts、summary_tasks 转为嵌套 dict。

    注意：调用方需确保 accounts 和 summary_tasks 关系已加载。
    """
    accounts = [a.username for a in orm.accounts] if orm.accounts else []

    summary_tasks = []
    if orm.summary_tasks:
        for task in orm.summary_tasks:
            task_dict: dict[str, Any] = {
                "time_span_hours": task.time_span_hours,
                "deadline": _dt_to_iso(task.deadline),
                "custom_prompt": task.custom_prompt,
                "tz_offset": task.tz_offset,
                "status": task.status,
                "error_message": task.error_message,
                "created_at": _dt_to_iso(task.created_at),
                "started_at": _dt_to_iso(task.started_at),
                "completed_at": _dt_to_iso(task.completed_at),
            }
            if task.summary:
                task_dict["summary"] = {
                    "content": task.summary.content,
                    "llm_provider": task.summary.llm_provider,
                    "llm_model": task.summary.llm_model,
                    "prompt_tokens": task.summary.prompt_tokens,
                    "completion_tokens": task.summary.completion_tokens,
                    "total_tokens": task.summary.total_tokens,
                    "cost_usd": task.summary.cost_usd,
                    "tweet_count": task.summary.tweet_count,
                    "account_count": task.summary.account_count,
                    "created_at": _dt_to_iso(task.summary.created_at),
                }
            else:
                task_dict["summary"] = None
            summary_tasks.append(task_dict)

    return {
        "name": orm.name,
        "description": orm.description,
        "accounts": accounts,
        "summary_tasks": summary_tasks,
    }


def dict_to_topic(d: dict[str, Any]) -> dict[str, Any]:
    """嵌套 dict → topic 构造参数（不含关联对象，由 import_repository 处理）。"""
    return {
        "name": d["name"],
        "description": d.get("description"),
        "accounts": d.get("accounts", []),
        "summary_tasks": d.get("summary_tasks", []),
    }
