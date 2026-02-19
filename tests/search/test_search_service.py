"""SearchService 单元测试。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.infrastructure.models import TweetOrm
from src.search.services.search_service import SearchService
from src.summarization.infrastructure.models import SummaryOrm


@pytest.fixture
async def search_data(async_session: AsyncSession):
    """准备搜索测试数据。

    推文：
    - tweet_1: user_a, "Python is great for AI", 引用推文含 "machine learning"
    - tweet_2: user_a, "FastAPI web framework"
    - tweet_3: user_b, "Rust performance benchmarks"
    - tweet_4: user_b, "Python and Rust interop"

    摘要：
    - tweet_1: 摘要="Python AI 开发指南", 翻译="Python AI development guide"
    - tweet_2: 摘要="FastAPI 框架介绍", 翻译=None
    - tweet_3: 无摘要
    - tweet_4: 无摘要
    """
    now = datetime.now(timezone.utc)
    base_time = now - timedelta(hours=2)

    tweets = [
        TweetOrm(
            tweet_id="search_t1",
            text="Python is great for AI",
            created_at=base_time + timedelta(minutes=40),
            db_created_at=base_time + timedelta(minutes=10),
            author_username="user_a",
            author_display_name="User A",
            reference_type="quoted",
            referenced_tweet_id="ref_t1",
            referenced_tweet_text="machine learning is the future",
            referenced_tweet_author_username="original_author",
            media=None,
        ),
        TweetOrm(
            tweet_id="search_t2",
            text="FastAPI web framework",
            created_at=base_time + timedelta(minutes=30),
            db_created_at=base_time + timedelta(minutes=20),
            author_username="user_a",
            author_display_name="User A",
            media=None,
        ),
        TweetOrm(
            tweet_id="search_t3",
            text="Rust performance benchmarks",
            created_at=base_time + timedelta(minutes=20),
            db_created_at=base_time + timedelta(minutes=30),
            author_username="user_b",
            author_display_name="User B",
            media=None,
        ),
        TweetOrm(
            tweet_id="search_t4",
            text="Python and Rust interop",
            created_at=base_time + timedelta(minutes=10),
            db_created_at=base_time + timedelta(minutes=40),
            author_username="user_b",
            author_display_name="User B",
            media=None,
        ),
    ]

    for tweet in tweets:
        async_session.add(tweet)
    await async_session.flush()

    summaries = [
        SummaryOrm(
            summary_id=str(uuid4()),
            tweet_id="search_t1",
            summary_text="Python AI 开发指南",
            translation_text="Python AI development guide",
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
            tweet_id="search_t2",
            summary_text="FastAPI 框架介绍",
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

    return {"tweets": tweets, "summaries": summaries, "base_time": base_time}


class TestSearchServiceKeyword:
    """测试关键词搜索。"""

    async def test_keyword_match_text(self, async_session, search_data):
        """关键词匹配推文正文。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="FastAPI")

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t2"

    async def test_keyword_match_referenced_text(self, async_session, search_data):
        """关键词匹配被引用推文正文。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="machine learning")

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t1"

    async def test_keyword_match_summary(self, async_session, search_data):
        """关键词匹配摘要字段。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="开发指南")

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t1"

    async def test_keyword_match_translation(self, async_session, search_data):
        """关键词匹配翻译字段。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="development guide")

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t1"

    async def test_keyword_multiple_matches(self, async_session, search_data):
        """关键词匹配多条推文。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="Python")

        assert result.total == 2
        ids = [item["tweet_id"] for item in result.items]
        assert "search_t1" in ids
        assert "search_t4" in ids

    async def test_multi_keyword_and_logic(self, async_session, search_data):
        """多关键词空格分隔，AND 逻辑。"""
        service = SearchService(async_session)
        # "Python" 匹配 t1 和 t4，"AI" 只匹配 t1 → AND 结果是 t1
        result = await service.search_tweets(q="Python AI")

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t1"

    async def test_keyword_no_match(self, async_session, search_data):
        """无匹配结果。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="不存在的内容xyz")

        assert result.total == 0
        assert result.items == []

    async def test_keyword_no_summary_mode(self, async_session, search_data):
        """include_summary=False 时不搜索摘要/翻译字段。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="开发指南", include_summary=False)

        assert result.total == 0


class TestSearchServiceAuthorFilter:
    """测试作者筛选。"""

    async def test_filter_by_author(self, async_session, search_data):
        """按单作者筛选。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="Python", author="user_a")

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t1"

    async def test_filter_by_author_case_insensitive(self, async_session, search_data):
        """作者筛选大小写不敏感。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="Python", author="User_A")

        assert result.total == 1

    async def test_filter_by_authors_list(self, async_session, search_data):
        """按多作者筛选。"""
        service = SearchService(async_session)
        result = await service.search_tweets(
            q="Python", authors=["user_a", "user_b"]
        )

        assert result.total == 2

    async def test_filter_author_no_match(self, async_session, search_data):
        """作者+关键词无交集。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="FastAPI", author="user_b")

        assert result.total == 0


class TestSearchServiceTimeRange:
    """测试时间范围筛选。"""

    async def test_filter_by_since(self, async_session, search_data):
        """since 过滤。"""
        base = search_data["base_time"]
        service = SearchService(async_session)
        # 只有 t1 (40min) 和 t2 (30min) 在 25min 之后
        result = await service.search_tweets(
            q="Python",
            since=base + timedelta(minutes=25),
        )

        # "Python" 匹配 t1(40min) 和 t4(10min)，since=25min 只保留 t1
        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t1"

    async def test_filter_by_until(self, async_session, search_data):
        """until 过滤。"""
        base = search_data["base_time"]
        service = SearchService(async_session)
        # "Python" 匹配 t1(40min) 和 t4(10min)，until=25min 只保留 t4
        result = await service.search_tweets(
            q="Python",
            until=base + timedelta(minutes=25),
        )

        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t4"

    async def test_filter_by_since_and_until(self, async_session, search_data):
        """同时指定 since 和 until。"""
        base = search_data["base_time"]
        service = SearchService(async_session)
        result = await service.search_tweets(
            q="Rust",
            since=base + timedelta(minutes=15),
            until=base + timedelta(minutes=25),
        )

        # "Rust" 匹配 t3(20min) 和 t4(10min)，时间范围 [15, 25) 只保留 t3
        assert result.total == 1
        assert result.items[0]["tweet_id"] == "search_t3"


class TestSearchServicePagination:
    """测试分页。"""

    async def test_page_1(self, async_session, search_data):
        """第一页。"""
        service = SearchService(async_session)
        # 搜索全部 4 条（用一个通用词）
        result = await service.search_tweets(q="t", page=1, page_size=2)

        assert result.total == 4
        assert len(result.items) == 2
        # 按 created_at desc: t1(40min), t2(30min)
        assert result.items[0]["tweet_id"] == "search_t1"
        assert result.items[1]["tweet_id"] == "search_t2"

    async def test_page_2(self, async_session, search_data):
        """第二页。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="t", page=2, page_size=2)

        assert result.total == 4
        assert len(result.items) == 2
        # t3(20min), t4(10min)
        assert result.items[0]["tweet_id"] == "search_t3"
        assert result.items[1]["tweet_id"] == "search_t4"

    async def test_page_beyond_total(self, async_session, search_data):
        """超出范围的页码返回空。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="Python", page=10, page_size=20)

        assert result.total == 2
        assert result.items == []


class TestSearchServiceOrdering:
    """测试排序。"""

    async def test_ordered_by_created_at_desc(self, async_session, search_data):
        """结果按 created_at 倒序。"""
        service = SearchService(async_session)
        result = await service.search_tweets(q="t", page_size=100)

        ids = [item["tweet_id"] for item in result.items]
        assert ids == ["search_t1", "search_t2", "search_t3", "search_t4"]
