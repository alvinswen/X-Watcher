# src/sync/infrastructure/export_serializers.py
"""候选侧导出序列化:domain → 与旧 serializers.*_to_dict 同构的 dict。

字段投影 + _dt_to_iso 时间戳格式逐字对齐旧 serializer(排除 auto-id/本地时间戳、保留业务时间戳)。
特殊投影:tweet media/referenced_tweet_media → list[dict](Media.model_dump);reference_type/status → .value。
"""

from __future__ import annotations

from datetime import datetime, timezone


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _media_list(xs):
    return [m.model_dump(mode="json") for m in xs] if xs else None


def follow_to_export_dict(f) -> dict:
    return {
        "username": f.username,
        "added_at": _dt_to_iso(f.added_at),
        "reason": f.reason,
        "added_by": f.added_by,
        "is_active": f.is_active,
        "manual_limit": f.manual_limit,
        "platform_user_id": f.platform_user_id,
        "brief_intro": f.brief_intro,
        "backfill_status": f.backfill_status,
        "backfill_completed_at": _dt_to_iso(f.backfill_completed_at),
    }


def tweet_to_export_dict(t) -> dict:
    return {
        "tweet_id": t.tweet_id,
        "text": t.text,
        "created_at": _dt_to_iso(t.created_at),
        "author_username": t.author_username,
        "author_display_name": t.author_display_name,
        "author_user_id": t.author_user_id,
        "referenced_tweet_id": t.referenced_tweet_id,
        "reference_type": t.reference_type.value if t.reference_type else None,
        "media": _media_list(t.media),
        "referenced_tweet_text": t.referenced_tweet_text,
        "referenced_tweet_media": _media_list(t.referenced_tweet_media),
        "referenced_tweet_author_username": t.referenced_tweet_author_username,
    }


def summary_to_export_dict(s) -> dict:
    return {
        "summary_id": s.summary_id,
        "tweet_id": s.tweet_id,
        "summary_text": s.summary_text,
        "translation_text": s.translation_text,
        "model_provider": s.model_provider,
        "model_name": s.model_name,
        "prompt_tokens": s.prompt_tokens,
        "completion_tokens": s.completion_tokens,
        "total_tokens": s.total_tokens,
        "cost_usd": s.cost_usd,
        "cached": s.cached,
        "is_generated_summary": s.is_generated_summary,
        "content_hash": s.content_hash,
        "created_at": _dt_to_iso(s.created_at),
    }


def article_to_export_dict(a) -> dict:
    return {
        "tweet_id": a.tweet_id,
        "title": a.title,
        "preview_text": a.preview_text,
        "cover_image_url": a.cover_image_url,
        "content": a.content,
        "content_html": a.content_html,
        "author_username": a.author_username,
        "fetched_at": _dt_to_iso(a.fetched_at),
    }
