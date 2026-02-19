"""去重结果浏览 API 集成测试。

测试 GET /api/deduplicate/groups 和 GET /api/deduplicate/stats/daily 端点。
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession, async_sessionmaker

from src.deduplication.api.routes import router as dedup_router
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.scraper.infrastructure.models import TweetOrm, DeduplicationGroupOrm


@pytest.fixture
def mock_admin_user():
    return UserDomain(
        id=1,
        name="admin",
        email="admin@test.com",
        is_admin=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def dedup_app(_test_db_engine, mock_admin_user):
    """创建带测试数据库的 FastAPI 应用。"""
    app = FastAPI()
    app.include_router(dedup_router)

    async def override_admin():
        return mock_admin_user

    app.dependency_overrides[get_current_admin_user] = override_admin

    test_session_maker = async_sessionmaker(
        _test_db_engine, class_=_AsyncSession, expire_on_commit=False
    )
    with patch(
        "src.deduplication.api.routes.get_async_session_maker",
        return_value=test_session_maker,
    ):
        yield app

    app.dependency_overrides.clear()


@pytest.fixture
async def dedup_client(dedup_app):
    async with AsyncClient(
        transport=ASGITransport(app=dedup_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def seed_dedup_data(async_session):
    """创建跨两天的推文和 3 个去重组。

    日期分布（UTC）：
    - 2026-02-15: tweet_1, tweet_2, tweet_3 → group_1 (exact), group_2 (exact)
    - 2026-02-16: tweet_4, tweet_5 → group_3 (similar)
    """
    day1 = datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 2, 16, 10, 0, 0, tzinfo=timezone.utc)

    tweets = [
        TweetOrm(
            tweet_id="t1", text="Hello world", author_username="alice",
            created_at=day1,
        ),
        TweetOrm(
            tweet_id="t2", text="Hello world", author_username="alice",
            created_at=day1 + timedelta(minutes=5),
        ),
        TweetOrm(
            tweet_id="t3", text="Goodbye world", author_username="bob",
            created_at=day1 + timedelta(hours=1),
        ),
        TweetOrm(
            tweet_id="t4", text="Similar text A", author_username="charlie",
            created_at=day2,
        ),
        TweetOrm(
            tweet_id="t5", text="Similar text B", author_username="charlie",
            created_at=day2 + timedelta(minutes=10),
        ),
    ]
    async_session.add_all(tweets)
    await async_session.flush()

    groups = [
        DeduplicationGroupOrm(
            group_id="g1",
            representative_tweet_id="t1",
            deduplication_type="exact_duplicate",
            similarity_score=None,
            tweet_ids=["t1", "t2"],
            created_at=day1 + timedelta(minutes=10),
        ),
        DeduplicationGroupOrm(
            group_id="g2",
            representative_tweet_id="t3",
            deduplication_type="exact_duplicate",
            similarity_score=None,
            tweet_ids=["t3"],
            created_at=day1 + timedelta(hours=2),
        ),
        DeduplicationGroupOrm(
            group_id="g3",
            representative_tweet_id="t4",
            deduplication_type="similar_content",
            similarity_score=0.92,
            tweet_ids=["t4", "t5"],
            created_at=day2 + timedelta(minutes=15),
        ),
    ]
    async_session.add_all(groups)
    await async_session.commit()


class TestListDeduplicationGroups:
    """测试 GET /api/deduplicate/groups 端点。"""

    @pytest.mark.asyncio
    async def test_list_all_groups(self, dedup_client, seed_dedup_data):
        """无筛选返回全部，按 created_at DESC 排序。"""
        response = await dedup_client.get("/api/deduplicate/groups")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_pages"] == 1
        assert len(data["items"]) == 3

        # 验证 DESC 排序：最新的 group 在前
        group_ids = [item["group_id"] for item in data["items"]]
        assert group_ids[0] == "g3"  # 2026-02-16
        assert group_ids[-1] == "g1"  # 2026-02-15 earliest

    @pytest.mark.asyncio
    async def test_filter_by_date(self, dedup_client, seed_dedup_data):
        """按 date 筛选（tz_offset=0 即 UTC）。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups", params={"date": "2026-02-15"}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 2
        group_ids = {item["group_id"] for item in data["items"]}
        assert group_ids == {"g1", "g2"}

    @pytest.mark.asyncio
    async def test_filter_by_type(self, dedup_client, seed_dedup_data):
        """按 deduplication_type 筛选。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups",
            params={"deduplication_type": "similar_content"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["group_id"] == "g3"
        assert data["items"][0]["deduplication_type"] == "similar_content"
        assert data["items"][0]["similarity_score"] == 0.92

    @pytest.mark.asyncio
    async def test_pagination(self, dedup_client, seed_dedup_data):
        """分页：page_size=2 验证 total_pages。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups", params={"page_size": 2, "page": 1}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 3
        assert data["total_pages"] == 2
        assert len(data["items"]) == 2

        # 第二页
        response2 = await dedup_client.get(
            "/api/deduplicate/groups", params={"page_size": 2, "page": 2}
        )
        data2 = response2.json()
        assert len(data2["items"]) == 1

    @pytest.mark.asyncio
    async def test_tweet_count_and_representative(self, dedup_client, seed_dedup_data):
        """验证 tweet_count 和 representative_tweet 字段。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups",
            params={"deduplication_type": "exact_duplicate"},
        )
        assert response.status_code == 200

        data = response.json()
        # g1 有 2 条推文
        g1_item = next(i for i in data["items"] if i["group_id"] == "g1")
        assert g1_item["tweet_count"] == 2
        assert g1_item["representative_tweet"]["tweet_id"] == "t1"
        assert g1_item["representative_tweet"]["text"] == "Hello world"
        assert g1_item["representative_tweet"]["author_username"] == "alice"

    @pytest.mark.asyncio
    async def test_no_results_date(self, dedup_client, seed_dedup_data):
        """无结果日期返回空列表。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups", params={"date": "2026-01-01"}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["total_pages"] == 0

    @pytest.mark.asyncio
    async def test_invalid_date_format(self, dedup_client, seed_dedup_data):
        """无效 date 格式返回 422。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups", params={"date": "2026/02/15"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_type(self, dedup_client, seed_dedup_data):
        """无效 deduplication_type 返回 422。"""
        response = await dedup_client.get(
            "/api/deduplicate/groups",
            params={"deduplication_type": "invalid_type"},
        )
        assert response.status_code == 422


class TestDailyDedupStats:
    """测试 GET /api/deduplicate/stats/daily 端点。"""

    @pytest.mark.asyncio
    async def test_monthly_stats(self, dedup_client, seed_dedup_data):
        """正常返回月度统计。"""
        response = await dedup_client.get(
            "/api/deduplicate/stats/daily",
            params={"year": 2026, "month": 2},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["year"] == 2026
        assert data["month"] == 2
        assert len(data["days"]) == 2

        # 验证日期和计数
        stats_map = {d["date"]: d["count"] for d in data["days"]}
        assert stats_map["2026-02-15"] == 2  # g1, g2
        assert stats_map["2026-02-16"] == 1  # g3

    @pytest.mark.asyncio
    async def test_empty_month(self, dedup_client, seed_dedup_data):
        """空月份返回空 days。"""
        response = await dedup_client.get(
            "/api/deduplicate/stats/daily",
            params={"year": 2026, "month": 1},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["days"] == []

    @pytest.mark.asyncio
    async def test_invalid_month(self, dedup_client):
        """无效 month 返回 422。"""
        response = await dedup_client.get(
            "/api/deduplicate/stats/daily",
            params={"year": 2026, "month": 13},
        )
        assert response.status_code == 422
