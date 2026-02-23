"""聚类分析 API 集成测试。"""

import pytest
from datetime import datetime, timezone

from fastapi import HTTPException, status

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperFollow
from src.scraper.infrastructure.models import TweetOrm


def _make_tweet(username: str, hour: int, idx: int = 0) -> TweetOrm:
    return TweetOrm(
        tweet_id=f"api_tweet_{username}_{hour}_{idx}",
        text=f"Test tweet",
        created_at=datetime(2024, 1, 15, hour, 30, 0, tzinfo=timezone.utc),
        author_username=username,
    )


async def _seed_data(session: AsyncSession) -> None:
    """创建测试数据：2 组账号。"""
    users = {
        "api_morning1": {6: 10, 7: 10, 8: 10},
        "api_morning2": {7: 10, 8: 10, 9: 10},
        "api_night1": {20: 10, 21: 10, 22: 10},
        "api_night2": {21: 10, 22: 10, 23: 10},
    }
    idx = 0
    for username, hour_counts in users.items():
        session.add(ScraperFollow(username=username, is_active=True, reason="test", added_by="test"))
        for hour, count in hour_counts.items():
            for i in range(count):
                session.add(_make_tweet(username, hour, idx))
                idx += 1
    await session.flush()


class TestClusteringApi:
    """测试聚类分析 API 端点。"""

    async def test_get_distributions(self, async_client: AsyncClient, async_session: AsyncSession):
        """GET /distributions 应返回分布数据。"""
        await _seed_data(async_session)

        response = await async_client.get("/api/admin/analytics/distributions")
        assert response.status_code == 200

        data = response.json()
        assert "distributions" in data
        assert "excluded" in data
        assert len(data["distributions"]) == 4

        for dist in data["distributions"]:
            assert len(dist["distribution"]) == 24
            assert dist["tweet_count"] >= 20

    async def test_run_clustering(self, async_client: AsyncClient, async_session: AsyncSession):
        """POST /clustering 应创建并返回聚类结果。"""
        await _seed_data(async_session)

        response = await async_client.post(
            "/api/admin/analytics/clustering",
            json={"min_tweets": 20},
        )
        assert response.status_code == 201

        data = response.json()
        assert data["status"] == "completed"
        assert data["num_clusters"] == 2
        assert data["num_accounts"] == 4
        assert len(data["assignments"]) == 4

    async def test_list_runs(self, async_client: AsyncClient, async_session: AsyncSession):
        """GET /clustering 应列出所有运行记录。"""
        await _seed_data(async_session)

        # 先创建一个运行
        await async_client.post("/api/admin/analytics/clustering", json={})

        response = await async_client.get("/api/admin/analytics/clustering")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_get_latest(self, async_client: AsyncClient, async_session: AsyncSession):
        """GET /clustering/latest 应返回最新完成的运行。"""
        await _seed_data(async_session)

        # 先创建一个运行
        await async_client.post("/api/admin/analytics/clustering", json={})

        response = await async_client.get("/api/admin/analytics/clustering/latest")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "completed"
        assert "assignments" in data

    async def test_get_latest_no_runs(self, async_client: AsyncClient):
        """GET /clustering/latest 无运行时应返回 404。"""
        response = await async_client.get("/api/admin/analytics/clustering/latest")
        assert response.status_code == 404

    async def test_get_run_by_id(self, async_client: AsyncClient, async_session: AsyncSession):
        """GET /clustering/{run_id} 应返回指定运行。"""
        await _seed_data(async_session)

        create_resp = await async_client.post("/api/admin/analytics/clustering", json={})
        run_id = create_resp.json()["id"]

        response = await async_client.get(f"/api/admin/analytics/clustering/{run_id}")
        assert response.status_code == 200
        assert response.json()["id"] == run_id

    async def test_get_nonexistent_run(self, async_client: AsyncClient):
        """GET /clustering/99999 应返回 404。"""
        response = await async_client.get("/api/admin/analytics/clustering/99999")
        assert response.status_code == 404

    async def test_recut(self, async_client: AsyncClient, async_session: AsyncSession):
        """POST /clustering/{id}/re-cut 应重切割并返回更新的结果。"""
        await _seed_data(async_session)

        create_resp = await async_client.post("/api/admin/analytics/clustering", json={})
        run_id = create_resp.json()["id"]
        original_clusters = create_resp.json()["num_clusters"]

        # 用非常小的 cut_height 强制更多组
        response = await async_client.post(
            f"/api/admin/analytics/clustering/{run_id}/re-cut",
            json={"cut_height": 0.001},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["num_clusters"] >= original_clusters

    async def test_move_account(self, async_client: AsyncClient, async_session: AsyncSession):
        """PUT /clustering/{id}/assignments/{username} 应移动账号。"""
        await _seed_data(async_session)

        create_resp = await async_client.post("/api/admin/analytics/clustering", json={})
        data = create_resp.json()
        run_id = data["id"]

        # 找一个账号及其当前组
        first_assignment = data["assignments"][0]
        username = first_assignment["username"]
        current_cluster = first_assignment["cluster_id"]
        target_cluster = 1 - current_cluster

        response = await async_client.put(
            f"/api/admin/analytics/clustering/{run_id}/assignments/{username}",
            json={"cluster_id": target_cluster},
        )
        assert response.status_code == 200
        assert response.json()["cluster_id"] == target_cluster
        assert response.json()["is_manual_override"] is True

    async def test_delete_run(self, async_client: AsyncClient, async_session: AsyncSession):
        """DELETE /clustering/{id} 应删除运行。"""
        await _seed_data(async_session)

        create_resp = await async_client.post("/api/admin/analytics/clustering", json={})
        run_id = create_resp.json()["id"]

        response = await async_client.delete(f"/api/admin/analytics/clustering/{run_id}")
        assert response.status_code == 204

        # 确认已删除
        response = await async_client.get(f"/api/admin/analytics/clustering/{run_id}")
        assert response.status_code == 404

    async def test_clustering_insufficient_accounts(
        self, async_client: AsyncClient, async_session: AsyncSession
    ):
        """只有 1 个有效账号时 POST /clustering 应返回 400。"""
        async_session.add(ScraperFollow(username="solo_api_user", is_active=True, reason="test", added_by="test"))
        idx = 0
        for hour in range(8, 12):
            for i in range(8):
                async_session.add(_make_tweet("solo_api_user", hour, idx))
                idx += 1
        await async_session.flush()

        response = await async_client.post(
            "/api/admin/analytics/clustering",
            json={"min_tweets": 20},
        )
        assert response.status_code == 400
        assert "有效账号不足" in response.json()["detail"]


class TestClusteringApiPermissions:
    """测试聚类分析 API 端点的权限控制。

    验证 admin analytics 端点拒绝非管理员用户（403）。
    """

    @pytest.fixture
    async def non_admin_client(self, async_session):
        """非管理员客户端 fixture：覆盖 get_current_admin_user 抛出 403。"""
        from httpx import ASGITransport, AsyncClient

        from src.database.async_session import get_db_session
        from src.main import app
        from src.user.api.auth import get_current_admin_user, get_current_user
        from src.user.domain.models import UserDomain

        non_admin = UserDomain(
            id=1, name="normal_user", email="user@test.com",
            is_admin=False, created_at=datetime.now(timezone.utc),
        )

        async def override_get_db_session():
            yield async_session

        async def override_get_current_user():
            return non_admin

        async def override_get_current_admin_user():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理员权限",
            )

        original_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db_session] = override_get_db_session
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                yield ac
        finally:
            app.dependency_overrides = original_overrides

    async def test_non_admin_cannot_get_distributions(self, non_admin_client):
        """非管理员访问 GET /distributions 应返回 403。"""
        resp = await non_admin_client.get("/api/admin/analytics/distributions")
        assert resp.status_code == 403

    async def test_non_admin_cannot_run_clustering(self, non_admin_client):
        """非管理员访问 POST /clustering 应返回 403。"""
        resp = await non_admin_client.post(
            "/api/admin/analytics/clustering", json={}
        )
        assert resp.status_code == 403

    async def test_non_admin_cannot_list_runs(self, non_admin_client):
        """非管理员访问 GET /clustering 应返回 403。"""
        resp = await non_admin_client.get("/api/admin/analytics/clustering")
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_run(self, non_admin_client):
        """非管理员访问 DELETE /clustering/{id} 应返回 403。"""
        resp = await non_admin_client.delete("/api/admin/analytics/clustering/1")
        assert resp.status_code == 403
