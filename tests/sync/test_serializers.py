"""Serializers 往返测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace

from src.sync.infrastructure.serializers import (
    article_to_dict,
    dict_to_article,
    dict_to_follow,
    dict_to_schedule_config,
    dict_to_summary,
    dict_to_tweet,
    follow_to_dict,
    schedule_config_to_dict,
    summary_to_dict,
    topic_to_dict,
    tweet_to_dict,
)


def _ns(**kwargs):
    """创建 SimpleNamespace 模拟 ORM 对象。"""
    return SimpleNamespace(**kwargs)


class TestFollowSerializer:
    def test_roundtrip(self):
        orm = _ns(
            username="alice",
            added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            reason="KOL",
            added_by="admin",
            is_active=True,
            manual_limit=50,
            platform_user_id="12345",
            brief_intro="AI 研究者",
            backfill_status="completed",
            backfill_completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        d = follow_to_dict(orm)
        assert d["username"] == "alice"
        assert d["manual_limit"] == 50

        result = dict_to_follow(d)
        assert result["username"] == "alice"
        assert result["added_at"] == datetime(2026, 1, 1)  # _iso_to_naive_dt 剥离时区
        assert result["manual_limit"] == 50

    def test_defaults(self):
        result = dict_to_follow({"username": "bob"})
        assert result["reason"] == ""
        assert result["added_by"] == "import"
        assert result["is_active"] is True


class TestScheduleConfigSerializer:
    def test_roundtrip(self):
        orm = _ns(
            interval_seconds=86400,
            next_run_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            is_enabled=False,
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            updated_by="admin",
        )
        d = schedule_config_to_dict(orm)
        result = dict_to_schedule_config(d)
        assert result["interval_seconds"] == 86400
        assert result["is_enabled"] is False


class TestTweetSerializer:
    def test_roundtrip(self):
        orm = _ns(
            tweet_id="tw_001",
            text="Hello world",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            author_username="alice",
            author_display_name="Alice",
            author_user_id="12345",
            referenced_tweet_id=None,
            reference_type=None,
            media=[{"type": "photo", "url": "https://example.com/img.jpg"}],
            referenced_tweet_text=None,
            referenced_tweet_media=None,
            referenced_tweet_author_username=None,
        )
        d = tweet_to_dict(orm)
        assert d["tweet_id"] == "tw_001"
        assert d["media"][0]["type"] == "photo"

        result = dict_to_tweet(d)
        assert result["tweet_id"] == "tw_001"
        assert result["created_at"] == datetime(2026, 2, 1, tzinfo=timezone.utc)

    def test_none_media(self):
        orm = _ns(
            tweet_id="tw_002",
            text="No media",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            author_username="bob",
            author_display_name=None,
            author_user_id=None,
            referenced_tweet_id=None,
            reference_type=None,
            media=None,
            referenced_tweet_text=None,
            referenced_tweet_media=None,
            referenced_tweet_author_username=None,
        )
        d = tweet_to_dict(orm)
        assert d["media"] is None
        result = dict_to_tweet(d)
        assert result["media"] is None


class TestSummarySerializer:
    def test_roundtrip(self):
        orm = _ns(
            summary_id="sum_001",
            tweet_id="tw_001",
            summary_text="这是一条摘要",
            translation_text="This is a summary",
            model_provider="openrouter",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.01,
            cached=False,
            is_generated_summary=True,
            content_hash="abc123",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        d = summary_to_dict(orm)
        result = dict_to_summary(d)
        assert result["summary_id"] == "sum_001"
        assert result["cost_usd"] == 0.01


class TestArticleSerializer:
    def test_roundtrip(self):
        orm = _ns(
            tweet_id="tw_003",
            title="Long Article",
            preview_text="Preview...",
            cover_image_url="https://example.com/cover.jpg",
            content="Full text content.",
            content_html="<p>Full text content.</p>",
            author_username="alice",
            fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        d = article_to_dict(orm)
        result = dict_to_article(d)
        assert result["tweet_id"] == "tw_003"
        assert result["title"] == "Long Article"


class TestTopicSerializer:
    def test_with_accounts_and_tasks(self):
        summary_orm = _ns(
            content="Summary content",
            llm_provider="openrouter",
            llm_model="gpt-4",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            cost_usd=0.02,
            tweet_count=10,
            account_count=3,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        task_orm = _ns(
            time_span_hours=24,
            deadline=datetime(2026, 2, 2, tzinfo=timezone.utc),
            custom_prompt=None,
            tz_offset=-480,
            status="completed",
            error_message=None,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            started_at=datetime(2026, 2, 1, 0, 5, tzinfo=timezone.utc),
            completed_at=datetime(2026, 2, 1, 0, 10, tzinfo=timezone.utc),
            summary=summary_orm,
        )
        topic_orm = _ns(
            name="AI Research",
            description="AI 研究动态",
            accounts=[_ns(username="alice"), _ns(username="bob")],
            summary_tasks=[task_orm],
        )
        d = topic_to_dict(topic_orm)
        assert d["name"] == "AI Research"
        assert d["accounts"] == ["alice", "bob"]
        assert len(d["summary_tasks"]) == 1
        assert d["summary_tasks"][0]["summary"]["tweet_count"] == 10

    def test_empty_relationships(self):
        topic_orm = _ns(
            name="Empty",
            description=None,
            accounts=[],
            summary_tasks=[],
        )
        d = topic_to_dict(topic_orm)
        assert d["accounts"] == []
        assert d["summary_tasks"] == []

    def test_task_without_summary(self):
        task_orm = _ns(
            time_span_hours=12,
            deadline=datetime(2026, 2, 2, tzinfo=timezone.utc),
            custom_prompt=None,
            tz_offset=0,
            status="pending",
            error_message=None,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            started_at=None,
            completed_at=None,
            summary=None,
        )
        topic_orm = _ns(
            name="Test",
            description=None,
            accounts=[],
            summary_tasks=[task_orm],
        )
        d = topic_to_dict(topic_orm)
        assert d["summary_tasks"][0]["summary"] is None
