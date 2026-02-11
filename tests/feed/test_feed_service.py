"""FeedService 单元测试。

测试推文+摘要联合查询逻辑。
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.feed.services.feed_service import FeedService
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm


@pytest.fixture
async def feed_data(async_session: AsyncSession):
    """准备 Feed 测试数据：3 条推文 + 2 条摘要。

    时间线（db_created_at）：
    - tweet_1: base + 10min
    - tweet_2: base + 20min
    - tweet_3: base + 30min

    摘要：
    - tweet_1: 有摘要 + 翻译
    - tweet_2: 有摘要，无翻译
    - tweet_3: 无摘要
    """
    now = datetime.now(timezone.utc)
    base_time = now - timedelta(hours=2)

    tweets = [
        TweetOrm(
            tweet_id="feed_tweet_1",
            text="First tweet",
            created_at=base_time + timedelta(minutes=30),
            db_created_at=base_time + timedelta(minutes=10),
            author_username="user1",
            author_display_name="User One",
            media=None,
        ),
        TweetOrm(
            tweet_id="feed_tweet_2",
            text="Second tweet",
            created_at=base_time + timedelta(minutes=20),
            db_created_at=base_time + timedelta(minutes=20),
            author_username="user1",
            author_display_name=None,
            media=None,
        ),
        TweetOrm(
            tweet_id="feed_tweet_3",
            text="Third tweet (no summary)",
            created_at=base_time + timedelta(minutes=10),
            db_created_at=base_time + timedelta(minutes=30),
            author_username="user2",
            author_display_name="User Two",
            media=None,
        ),
    ]

    for tweet in tweets:
        async_session.add(tweet)
    await async_session.flush()

    summaries = [
        SummaryOrm(
            summary_id=str(uuid4()),
            tweet_id="feed_tweet_1",
            summary_text="摘要1",
            translation_text="翻译1",
            model_provider="minimax",
            model_name="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=False,
            is_generated_summary=True,
            content_hash="hash1",
        ),
        SummaryOrm(
            summary_id=str(uuid4()),
            tweet_id="feed_tweet_2",
            summary_text="摘要2",
            translation_text=None,
            model_provider="minimax",
            model_name="test-model",
            prompt_tokens=80,
            completion_tokens=40,
            total_tokens=120,
            cost_usd=0.001,
            cached=False,
            is_generated_summary=True,
            content_hash="hash2",
        ),
    ]

    for summary in summaries:
        async_session.add(summary)
    await async_session.commit()

    return {
        "tweets": tweets,
        "summaries": summaries,
        "base_time": base_time,
    }


class TestFeedServiceTimeFiltering:
    """测试时间区间过滤。"""

    async def test_since_until_boundary(self, async_session, feed_data):
        """验证 since/until 边界过滤：仅返回 db_created_at 在 [since, until) 区间的推文。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        # 仅包含 tweet_2 (db_created_at = base + 20min)
        result = await service.get_feed(
            since=base + timedelta(minutes=15),
            until=base + timedelta(minutes=25),
            limit=100,
        )

        assert result.total == 1
        assert result.count == 1
        assert result.items[0]["tweet_id"] == "feed_tweet_2"

    async def test_all_tweets_in_range(self, async_session, feed_data):
        """验证查询全部推文。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=100,
        )

        assert result.total == 3
        assert result.count == 3

    async def test_empty_result(self, async_session, feed_data):
        """验证无匹配数据时返回空结果。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base - timedelta(hours=10),
            until=base - timedelta(hours=9),
            limit=100,
        )

        assert result.items == []
        assert result.count == 0
        assert result.total == 0
        assert result.has_more is False


class TestFeedServiceSummary:
    """测试摘要加载行为。"""

    async def test_include_summary_true(self, async_session, feed_data):
        """include_summary=true 时返回摘要和翻译字段。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=100,
            include_summary=True,
        )

        # 按 created_at DESC 排序: tweet_1 (30min) > tweet_2 (20min) > tweet_3 (10min)
        items_by_id = {item["tweet_id"]: item for item in result.items}

        assert items_by_id["feed_tweet_1"]["summary_text"] == "摘要1"
        assert items_by_id["feed_tweet_1"]["translation_text"] == "翻译1"
        assert items_by_id["feed_tweet_2"]["summary_text"] == "摘要2"
        assert items_by_id["feed_tweet_2"]["translation_text"] is None

    async def test_include_summary_false(self, async_session, feed_data):
        """include_summary=false 时 summary_text 和 translation_text 为 null。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=100,
            include_summary=False,
        )

        for item in result.items:
            assert item["summary_text"] is None
            assert item["translation_text"] is None

    async def test_no_summary_returns_null(self, async_session, feed_data):
        """无摘要记录的推文，summary 字段为 null（LEFT JOIN 特性）。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=100,
            include_summary=True,
        )

        items_by_id = {item["tweet_id"]: item for item in result.items}
        assert items_by_id["feed_tweet_3"]["summary_text"] is None
        assert items_by_id["feed_tweet_3"]["translation_text"] is None


class TestFeedServiceLimitAndHasMore:
    """测试 limit 截断和 has_more 标志。"""

    async def test_limit_truncation_has_more_true(self, async_session, feed_data):
        """limit 小于总数时，has_more=True。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=2,
        )

        assert result.count == 2
        assert result.total == 3
        assert result.has_more is True

    async def test_all_returned_has_more_false(self, async_session, feed_data):
        """全部返回时，has_more=False。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=10,
        )

        assert result.count == 3
        assert result.total == 3
        assert result.has_more is False


class TestFeedServiceOrdering:
    """测试排序。"""

    async def test_ordered_by_created_at_desc(self, async_session, feed_data):
        """验证结果按 created_at 倒序排列。"""
        base = feed_data["base_time"]
        service = FeedService(async_session)

        result = await service.get_feed(
            since=base,
            until=base + timedelta(hours=1),
            limit=100,
        )

        tweet_ids = [item["tweet_id"] for item in result.items]
        # created_at 顺序: tweet_1 (30min) > tweet_2 (20min) > tweet_3 (10min)
        assert tweet_ids == ["feed_tweet_1", "feed_tweet_2", "feed_tweet_3"]
