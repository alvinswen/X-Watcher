"""聚类业务逻辑。"""

import json
import logging
from datetime import datetime, timezone

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import jensenshannon, squareform
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.domain.models import AccountDistribution, ClusteringRunStatus
from src.analytics.infrastructure.models import ClusterAssignmentOrm, ClusteringRunOrm
from src.analytics.infrastructure.repository import ClusteringRepository
from src.analytics.services.feature_engineering import build_hourly_distributions
from src.database.models import ScraperFollow
from sqlalchemy import select

logger = logging.getLogger(__name__)


class ClusteringService:
    """聚类分析服务。"""

    def __init__(self) -> None:
        self._repo = ClusteringRepository()

    async def get_active_usernames(self, session: AsyncSession) -> list[str]:
        """获取所有活跃监控账号的用户名。"""
        stmt = select(ScraperFollow.username).where(ScraperFollow.is_active.is_(True))
        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    async def get_distributions(
        self, session: AsyncSession, min_tweets: int = 20
    ) -> tuple[list[AccountDistribution], list[str]]:
        """获取所有活跃账号的分布向量（预览用）。"""
        usernames = await self.get_active_usernames(session)
        if not usernames:
            return [], []
        return await build_hourly_distributions(session, usernames, min_tweets)

    async def run_clustering(
        self,
        session: AsyncSession,
        min_tweets: int = 20,
        linkage_method: str = "average",
        cut_height: float | None = None,
        num_clusters: int | None = None,
    ) -> ClusteringRunOrm:
        """执行一次完整的聚类分析。"""
        # 创建运行记录
        run = ClusteringRunOrm(
            status=ClusteringRunStatus.running.value,
            min_tweets_threshold=min_tweets,
            linkage_method=linkage_method,
        )
        run = await self._repo.create_run(session, run)

        try:
            # 获取活跃账号
            usernames = await self.get_active_usernames(session)
            distributions, excluded = await build_hourly_distributions(
                session, usernames, min_tweets
            )

            if len(distributions) < 2:
                raise ValueError(
                    f"有效账号不足（需要至少 2 个，当前 {len(distributions)} 个），"
                    f"已排除 {len(excluded)} 个数据不足的账号"
                )

            # 构建距离矩阵
            n = len(distributions)
            dist_matrix = np.zeros((n, n))
            vectors = [np.array(d.distribution) for d in distributions]

            for i in range(n):
                for j in range(i + 1, n):
                    dist_matrix[i, j] = jensenshannon(vectors[i], vectors[j])
                    dist_matrix[j, i] = dist_matrix[i, j]

            # 层次聚类
            condensed = squareform(dist_matrix)
            Z = linkage(condensed, method=linkage_method)

            # 确定切割高度
            max_dist = Z[:, 2].max() if len(Z) > 0 else 0
            if cut_height is not None:
                actual_cut = cut_height
            elif num_clusters is not None:
                labels = fcluster(Z, t=num_clusters, criterion="maxclust")
                actual_cut = None
            else:
                actual_cut = 0.7 * max_dist

            # 执行切割
            if actual_cut is not None:
                labels = fcluster(Z, t=actual_cut, criterion="distance")
            actual_num_clusters = len(set(labels))

            # 更新运行记录
            run.status = ClusteringRunStatus.completed.value
            run.cut_height = actual_cut if actual_cut is not None else float(max_dist * 0.7)
            run.num_clusters = actual_num_clusters
            run.num_accounts = len(distributions)
            run.num_excluded = len(excluded)
            run.linkage_matrix_json = json.dumps(Z.tolist())
            run.account_labels_json = json.dumps([d.username for d in distributions])
            run.completed_at = datetime.now(timezone.utc)

            # 创建分配记录
            for i, dist in enumerate(distributions):
                assignment = ClusterAssignmentOrm(
                    run_id=run.id,
                    username=dist.username,
                    cluster_id=int(labels[i]) - 1,  # fcluster 从 1 开始，我们从 0 开始
                    hourly_distribution_json=json.dumps(dist.distribution),
                    tweet_count=dist.tweet_count,
                    is_manual_override=False,
                )
                session.add(assignment)

            await session.flush()
            await self._repo.update_run(session, run)
            await session.commit()

            # 重新加载带 assignments 的完整记录
            return await self._repo.get_run(session, run.id)  # type: ignore[return-value]

        except Exception as e:
            run.status = ClusteringRunStatus.failed.value
            run.error_message = str(e)
            run.completed_at = datetime.now(timezone.utc)
            await self._repo.update_run(session, run)
            await session.commit()
            raise

    async def recut(
        self,
        session: AsyncSession,
        run_id: int,
        cut_height: float | None = None,
        num_clusters: int | None = None,
    ) -> ClusteringRunOrm:
        """重切割已有的聚类运行（不重新计算 linkage matrix）。"""
        run = await self._repo.get_run(session, run_id)
        if not run:
            raise ValueError("聚类运行不存在")
        if run.status != ClusteringRunStatus.completed.value:
            raise ValueError("只能对已完成的运行进行重切割")
        if not run.linkage_matrix_json:
            raise ValueError("该运行缺少 linkage matrix 数据")

        Z = np.array(json.loads(run.linkage_matrix_json))

        # 确定新的切割
        if cut_height is not None:
            labels = fcluster(Z, t=cut_height, criterion="distance")
        elif num_clusters is not None:
            labels = fcluster(Z, t=num_clusters, criterion="maxclust")
        else:
            raise ValueError("必须指定 cut_height 或 num_clusters")

        # 收集手动 override 的账号
        manual_overrides: dict[str, int] = {}
        for a in run.assignments:
            if a.is_manual_override:
                manual_overrides[a.username] = a.cluster_id

        # 重建分配
        account_labels = json.loads(run.account_labels_json) if run.account_labels_json else []

        # 构建用户名到分布的映射
        dist_map: dict[str, tuple[str, int]] = {}
        for a in run.assignments:
            dist_map[a.username] = (a.hourly_distribution_json, a.tweet_count)

        # 删除旧分配并创建新的
        await self._repo.delete_assignments_for_run(session, run_id)

        new_assignments: list[ClusterAssignmentOrm] = []
        for i, username in enumerate(account_labels):
            if username in manual_overrides:
                cluster_id = manual_overrides[username]
                is_override = True
            else:
                cluster_id = int(labels[i]) - 1
                is_override = False

            dist_json, tweet_count = dist_map.get(username, ("[]", 0))
            new_assignments.append(
                ClusterAssignmentOrm(
                    run_id=run_id,
                    username=username,
                    cluster_id=cluster_id,
                    hourly_distribution_json=dist_json,
                    tweet_count=tweet_count,
                    is_manual_override=is_override,
                )
            )

        await self._repo.bulk_create_assignments(session, new_assignments)

        # 更新运行记录
        run.cut_height = cut_height
        run.num_clusters = len(set(a.cluster_id for a in new_assignments))
        await self._repo.update_run(session, run)
        await session.commit()

        return await self._repo.get_run(session, run_id)  # type: ignore[return-value]

    async def move_account(
        self,
        session: AsyncSession,
        run_id: int,
        username: str,
        target_cluster_id: int,
    ) -> ClusterAssignmentOrm:
        """手动将账号移到其他聚类组。"""
        assignment = await self._repo.get_assignment(session, run_id, username)
        if not assignment:
            raise ValueError(f"账号 '{username}' 在运行 {run_id} 中不存在")

        assignment.cluster_id = target_cluster_id
        assignment.is_manual_override = True
        await session.flush()
        await session.commit()
        return assignment

    async def list_runs(self, session: AsyncSession) -> list[ClusteringRunOrm]:
        """列出所有聚类运行。"""
        return await self._repo.list_runs(session)

    async def get_run(self, session: AsyncSession, run_id: int) -> ClusteringRunOrm | None:
        """获取指定运行的完整详情。"""
        return await self._repo.get_run(session, run_id)

    async def get_latest_completed(self, session: AsyncSession) -> ClusteringRunOrm | None:
        """获取最近一次完成的聚类运行。"""
        return await self._repo.get_latest_completed(session)

    async def delete_run(self, session: AsyncSession, run_id: int) -> bool:
        """删除指定的聚类运行。"""
        result = await self._repo.delete_run(session, run_id)
        if result:
            await session.commit()
        return result
