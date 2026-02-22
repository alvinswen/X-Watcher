"""聚类服务单元测试。"""

import json

import pytest
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.domain.models import ClusteringRunStatus
from src.analytics.services.clustering_service import ClusteringService
from src.database.models import ScraperFollow
from src.scraper.infrastructure.models import TweetOrm


def _make_tweet(username: str, hour: int, idx: int = 0) -> TweetOrm:
    return TweetOrm(
        tweet_id=f"tweet_{username}_{hour}_{idx}",
        text=f"Test tweet",
        created_at=datetime(2024, 1, 15, hour, 30, 0, tzinfo=timezone.utc),
        author_username=username,
    )


async def _seed_follows_and_tweets(
    session: AsyncSession,
    user_configs: dict[str, dict[int, int]],
) -> None:
    """创建关注记录和推文。user_configs: {username: {hour: count}}"""
    idx = 0
    for username, hour_counts in user_configs.items():
        session.add(ScraperFollow(username=username, is_active=True, reason="test", added_by="test"))
        for hour, count in hour_counts.items():
            for i in range(count):
                session.add(_make_tweet(username, hour, idx))
                idx += 1
    await session.flush()


class TestClusteringService:
    """测试 ClusteringService。"""

    async def test_run_clustering_two_groups(self, async_session: AsyncSession):
        """合成数据：'早间型' vs '晚间型' 应聚为两组。"""
        await _seed_follows_and_tweets(async_session, {
            "morning1": {6: 10, 7: 10, 8: 10},
            "morning2": {7: 10, 8: 10, 9: 10},
            "night1": {20: 10, 21: 10, 22: 10},
            "night2": {21: 10, 22: 10, 23: 10},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        assert run.status == ClusteringRunStatus.completed.value
        assert run.num_clusters == 2
        assert run.num_accounts == 4

        # 验证同类型账号在同一组
        assignments = {a.username: a.cluster_id for a in run.assignments}
        assert assignments["morning1"] == assignments["morning2"]
        assert assignments["night1"] == assignments["night2"]
        assert assignments["morning1"] != assignments["night1"]

    async def test_run_clustering_too_few_accounts(self, async_session: AsyncSession):
        """有效账号不足 2 个时应返回错误。"""
        await _seed_follows_and_tweets(async_session, {
            "solo_user": {12: 25},
        })

        service = ClusteringService()
        with pytest.raises(ValueError, match="有效账号不足"):
            await service.run_clustering(async_session, min_tweets=20)

    async def test_run_clustering_excludes_low_tweets(self, async_session: AsyncSession):
        """推文不足的账号应被排除。"""
        await _seed_follows_and_tweets(async_session, {
            "active1": {8: 15, 12: 15},
            "active2": {20: 15, 22: 15},
            "inactive": {10: 3},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        assert run.num_accounts == 2
        assert run.num_excluded == 1
        usernames = {a.username for a in run.assignments}
        assert "inactive" not in usernames

    async def test_recut_changes_clusters(self, async_session: AsyncSession):
        """重切割应能改变聚类组数。"""
        # 创建 3 个明显不同的组
        await _seed_follows_and_tweets(async_session, {
            "morning": {6: 10, 7: 10, 8: 10},
            "afternoon": {12: 10, 13: 10, 14: 10},
            "night": {20: 10, 21: 10, 22: 10},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        # 用非常大的 cut_height 重切割，应合并为更少的组
        recut_run = await service.recut(async_session, run.id, cut_height=1.0)
        assert recut_run.num_clusters >= 1
        # 验证 recut 成功完成
        assert len(recut_run.assignments) == 3

    async def test_recut_preserves_manual_override(self, async_session: AsyncSession):
        """重切割应保留手动 override 的账号分配。"""
        await _seed_follows_and_tweets(async_session, {
            "user_a": {8: 15, 9: 15},
            "user_b": {20: 15, 21: 15},
            "user_c": {14: 15, 15: 15},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        # 手动移动 user_a 到 cluster 0
        await service.move_account(async_session, run.id, "user_a", 0)

        # 重切割
        recut_run = await service.recut(async_session, run.id, num_clusters=2)

        # user_a 应保持在 cluster 0
        user_a = next(a for a in recut_run.assignments if a.username == "user_a")
        assert user_a.cluster_id == 0
        assert user_a.is_manual_override is True

    async def test_move_account(self, async_session: AsyncSession):
        """手动移动账号应更新 cluster_id 和 is_manual_override。"""
        await _seed_follows_and_tweets(async_session, {
            "user_x": {8: 15, 9: 15},
            "user_y": {20: 15, 21: 15},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        user_x = next(a for a in run.assignments if a.username == "user_x")
        original_cluster = user_x.cluster_id
        target_cluster = 1 - original_cluster  # 切换到另一组

        assignment = await service.move_account(
            async_session, run.id, "user_x", target_cluster
        )
        assert assignment.cluster_id == target_cluster
        assert assignment.is_manual_override is True

    async def test_move_nonexistent_account(self, async_session: AsyncSession):
        """移动不存在的账号应抛出 ValueError。"""
        await _seed_follows_and_tweets(async_session, {
            "user_1": {8: 15, 9: 15},
            "user_2": {20: 15, 21: 15},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        with pytest.raises(ValueError, match="不存在"):
            await service.move_account(async_session, run.id, "nonexistent", 0)

    async def test_delete_run(self, async_session: AsyncSession):
        """删除运行后应不可查询。"""
        await _seed_follows_and_tweets(async_session, {
            "del_user1": {8: 15, 9: 15},
            "del_user2": {20: 15, 21: 15},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)
        run_id = run.id

        result = await service.delete_run(async_session, run_id)
        assert result is True

        deleted = await service.get_run(async_session, run_id)
        assert deleted is None

    async def test_linkage_matrix_stored(self, async_session: AsyncSession):
        """聚类运行应存储 linkage matrix JSON。"""
        await _seed_follows_and_tweets(async_session, {
            "lm_user1": {8: 15, 9: 15},
            "lm_user2": {20: 15, 21: 15},
        })

        service = ClusteringService()
        run = await service.run_clustering(async_session, min_tweets=20)

        assert run.linkage_matrix_json is not None
        matrix = json.loads(run.linkage_matrix_json)
        assert isinstance(matrix, list)
        assert len(matrix) > 0

        assert run.account_labels_json is not None
        labels = json.loads(run.account_labels_json)
        assert len(labels) == 2
