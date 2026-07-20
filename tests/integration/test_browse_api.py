"""Browse API 集成测试。

测试推文浏览 API 端点的完整调用链：HTTP → 认证 → 查询 → 响应格式。
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from starlette import status

from src.config import clear_settings_cache
from src.main import app
from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.domain.models import Media, Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore


@pytest.fixture(autouse=True)
def file_data_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
async def seed_browse_data():
    """准备浏览测试数据。

    创建跨两天、两个作者的推文，部分推文有摘要。
    """
    # 2026-02-15 的推文
    day1 = datetime(2026, 2, 15, 10, 0, 0, tzinfo=UTC)
    # 2026-02-16 的推文
    day2 = datetime(2026, 2, 16, 8, 0, 0, tzinfo=UTC)

    tweets = [
        # Day 1: user_a 2条, user_b 1条
        Tweet(
            tweet_id="browse_t1",
            text="Day 1 tweet 1 from user_a",
            created_at=day1,
            author_username="user_a",
            author_display_name="User A",
            media=None,
        ),
        Tweet(
            tweet_id="browse_t2",
            text="Day 1 tweet 2 from user_a",
            created_at=day1 + timedelta(hours=2),
            author_username="user_a",
            author_display_name="User A",
            media=[Media(media_key="browse_m1", url="https://example.com/img.jpg", type="photo")],
        ),
        Tweet(
            tweet_id="browse_t3",
            text="Day 1 tweet from user_b",
            created_at=day1 + timedelta(hours=3),
            author_username="user_b",
            author_display_name="User B",
            media=None,
            reference_type="quoted",
            referenced_tweet_id="ref_original",
            referenced_tweet_text="Original quoted text",
            referenced_tweet_author_username="original_author",
        ),
        # Day 2: user_a 1条
        Tweet(
            tweet_id="browse_t4",
            text="Day 2 tweet from user_a",
            created_at=day2,
            author_username="user_a",
            author_display_name="User A Updated",
            media=None,
        ),
    ]

    root = Path(os.environ["XWATCHER_DATA_ROOT"])
    await FileTweetStore(root).save_tweets(tweets, early_stop_threshold=0)

    # 为第1条推文添加摘要
    summary = SummaryRecord(
        summary_id=str(uuid4()),
        tweet_id="browse_t1",
        summary_text="这是第一条推文的摘要",
        translation_text="这是翻译内容",
        model_provider="test",
        model_name="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        cached=False,
        is_generated_summary=True,
        content_hash="test_hash_browse_t1",
        created_at=day1,
        updated_at=day1,
    )
    await FileSummaryStore(root).seed([summary])

    # 添加 ScraperFollow 记录（作者简介）
    follows = [
        ScraperFollow(
            id=1,
            username="user_a",
            added_at=day1,
            reason="AI researcher, focus on LLMs",
            added_by="admin",
            is_active=True,
        ),
        ScraperFollow(
            id=2,
            username="user_b",
            added_at=day1 + timedelta(minutes=1),
            reason="Crypto analyst",
            added_by="admin",
            is_active=True,
        ),
    ]
    await FileFollowStore(root).seed(follows)


@pytest.mark.asyncio
class TestBrowseDailyStats:
    """测试每日统计端点。"""

    async def test_daily_stats_success(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """正常查询 2026 年 2 月的每日统计。"""
        response = await async_client.get(
            "/api/browse/stats/daily", params={"year": 2026, "month": 2}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["year"] == 2026
        assert data["month"] == 2
        assert isinstance(data["days"], list)

        # 应有 2 天有推文
        dates = {d["date"]: d["count"] for d in data["days"]}
        assert dates.get("2026-02-15") == 3
        assert dates.get("2026-02-16") == 1

    async def test_daily_stats_empty_month(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """查询无推文的月份返回空列表。"""
        response = await async_client.get(
            "/api/browse/stats/daily", params={"year": 2025, "month": 1}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["days"] == []

    async def test_daily_stats_invalid_month(
        self, async_client: AsyncClient
    ):
        """无效月份返回 422。"""
        response = await async_client.get(
            "/api/browse/stats/daily", params={"year": 2026, "month": 13}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_daily_stats_month_zero(
        self, async_client: AsyncClient
    ):
        """月份为 0 返回 422。"""
        response = await async_client.get(
            "/api/browse/stats/daily", params={"year": 2026, "month": 0}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
class TestBrowseAuthors:
    """测试作者列表端点。"""

    async def test_authors_success(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """查询 2026-02-15 的作者列表。"""
        response = await async_client.get(
            "/api/browse/authors", params={"date": "2026-02-15"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 2
        assert len(data["authors"]) == 2

        # 按最后活跃时间降序：user_b (13:00) > user_a (12:00)
        assert data["authors"][0]["author_username"] == "user_b"
        assert data["authors"][0]["reason"] == "Crypto analyst"
        assert data["authors"][1]["author_username"] == "user_a"
        assert data["authors"][1]["reason"] == "AI researcher, focus on LLMs"
        assert data["authors"][1]["tweet_count"] == 2

    async def test_authors_empty_date(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """查询无推文的日期返回空列表。"""
        response = await async_client.get(
            "/api/browse/authors", params={"date": "2026-02-14"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 0
        assert data["authors"] == []

    async def test_authors_invalid_date_format(
        self, async_client: AsyncClient
    ):
        """无效日期格式返回 422。"""
        response = await async_client.get(
            "/api/browse/authors", params={"date": "2026/02/15"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_authors_display_name(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """验证 display_name 来自当天最新推文。"""
        response = await async_client.get(
            "/api/browse/authors", params={"date": "2026-02-15"}
        )
        data = response.json()
        user_a = next(
            a for a in data["authors"] if a["author_username"] == "user_a"
        )
        assert user_a["author_display_name"] == "User A"

    async def test_authors_reason_missing(
        self, async_client: AsyncClient
    ):
        """没有 ScraperFollow 记录的作者，reason 应为 null。"""
        day = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
        tweet = Tweet(
            tweet_id="browse_orphan",
            text="Tweet from unknown author",
            created_at=day,
            author_username="unknown_user",
            author_display_name="Unknown",
            media=None,
        )
        await FileTweetStore(Path(os.environ["XWATCHER_DATA_ROOT"])).save_tweets(
            [tweet], early_stop_threshold=0
        )

        response = await async_client.get(
            "/api/browse/authors", params={"date": "2026-03-01"}
        )
        data = response.json()
        assert data["total"] == 1
        assert data["authors"][0]["reason"] is None


@pytest.mark.asyncio
class TestBrowseTweets:
    """测试推文浏览列表端点。"""

    async def test_tweets_success(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """查询 2026-02-15 的推文列表。"""
        response = await async_client.get(
            "/api/browse/tweets", params={"date": "2026-02-15"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert len(data["items"]) == 3

        # 按时间正序排列
        assert data["items"][0]["tweet_id"] == "browse_t1"
        assert data["items"][1]["tweet_id"] == "browse_t2"
        assert data["items"][2]["tweet_id"] == "browse_t3"

    async def test_tweets_with_summary(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """验证推文包含摘要和翻译。"""
        response = await async_client.get(
            "/api/browse/tweets", params={"date": "2026-02-15"}
        )
        data = response.json()

        # 第一条推文有摘要
        t1 = data["items"][0]
        assert t1["summary_text"] == "这是第一条推文的摘要"
        assert t1["translation_text"] == "这是翻译内容"

        # 第二条推文无摘要
        t2 = data["items"][1]
        assert t2["summary_text"] is None
        assert t2["translation_text"] is None

    async def test_tweets_author_filter(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """按作者筛选推文。"""
        response = await async_client.get(
            "/api/browse/tweets",
            params={"date": "2026-02-15", "author": "user_a"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 2
        assert all(
            item["author_username"] == "user_a" for item in data["items"]
        )

    async def test_tweets_with_reference(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """验证引用推文信息。"""
        response = await async_client.get(
            "/api/browse/tweets",
            params={"date": "2026-02-15", "author": "user_b"},
        )
        data = response.json()
        assert len(data["items"]) == 1

        t3 = data["items"][0]
        assert t3["reference_type"] == "quoted"
        assert t3["referenced_tweet_id"] == "ref_original"
        assert t3["referenced_tweet_text"] == "Original quoted text"
        assert t3["referenced_tweet_author_username"] == "original_author"

    async def test_tweets_with_media(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """验证媒体附件。"""
        response = await async_client.get(
            "/api/browse/tweets", params={"date": "2026-02-15"}
        )
        data = response.json()

        # 第二条推文有媒体
        t2 = data["items"][1]
        assert t2["media"] is not None
        assert len(t2["media"]) == 1

    async def test_tweets_pagination(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """测试分页。"""
        # 每页 2 条
        response = await async_client.get(
            "/api/browse/tweets",
            params={"date": "2026-02-15", "page": 1, "page_size": 2},
        )
        data = response.json()
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 2
        assert len(data["items"]) == 2

        # 第二页
        response2 = await async_client.get(
            "/api/browse/tweets",
            params={"date": "2026-02-15", "page": 2, "page_size": 2},
        )
        data2 = response2.json()
        assert len(data2["items"]) == 1
        assert data2["items"][0]["tweet_id"] == "browse_t3"

    async def test_tweets_empty_date(
        self, async_client: AsyncClient, seed_browse_data
    ):
        """查询无推文的日期返回空列表。"""
        response = await async_client.get(
            "/api/browse/tweets", params={"date": "2026-02-14"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["total_pages"] == 0

    async def test_tweets_invalid_date_format(
        self, async_client: AsyncClient
    ):
        """无效日期格式返回 422。"""
        response = await async_client.get(
            "/api/browse/tweets", params={"date": "20260215"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
class TestBrowseAuth:
    """测试认证。"""

    async def test_no_auth_returns_error(self):
        """无认证访问返回错误。"""
        # 不覆写 admin auth，应使用原始的认证逻辑

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get(
                "/api/browse/stats/daily", params={"year": 2026, "month": 2}
            )
            # 无 API Key 应返回 401 或 403
            assert response.status_code in (
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            )
