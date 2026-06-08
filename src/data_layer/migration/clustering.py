"""clustering 单元迁移:clustering_runs + cluster_assignments → clustering.json。

FileClusteringStore.seed(runs, assignments) 一次收两集合(与 topic 不同,无需补丁)。
域/ORM 字段 1:1(runs 13 / assignments 7),无 dropped。
created_at/completed_at 是 DateTime(无 tz)=naive,naive() 幂等;status str→enum coerce。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.analytics.domain.models import ClusterAssignmentDomain, ClusteringRunDomain
from src.analytics.infrastructure.file_clustering_repository import FileClusteringStore
from src.analytics.infrastructure.models import ClusterAssignmentOrm, ClusteringRunOrm
from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register


def _run_to_domain(o: ClusteringRunOrm) -> ClusteringRunDomain:
    return ClusteringRunDomain(
        id=o.id, status=o.status, cut_height=o.cut_height, num_clusters=o.num_clusters,
        num_accounts=o.num_accounts, num_excluded=o.num_excluded,
        min_tweets_threshold=o.min_tweets_threshold, linkage_method=o.linkage_method,
        linkage_matrix_json=o.linkage_matrix_json, account_labels_json=o.account_labels_json,
        error_message=o.error_message, created_at=naive(o.created_at),
        completed_at=naive(o.completed_at),
    )


def _assignment_to_domain(o: ClusterAssignmentOrm) -> ClusterAssignmentDomain:
    return ClusterAssignmentDomain(
        id=o.id, run_id=o.run_id, username=o.username, cluster_id=o.cluster_id,
        hourly_distribution_json=o.hourly_distribution_json, tweet_count=o.tweet_count,
        is_manual_override=o.is_manual_override,
    )


@register("clustering")
async def migrate_clustering(session, data_root: Path) -> MigrationReport:
    run_rows = (await session.execute(select(ClusteringRunOrm))).scalars().all()
    assign_rows = (await session.execute(select(ClusterAssignmentOrm))).scalars().all()
    rep = MigrationReport(entity="clustering", pg_count=len(run_rows) + len(assign_rows))
    store = FileClusteringStore(data_root)
    store._path.unlink(missing_ok=True)
    runs = [_run_to_domain(o) for o in run_rows]
    assignments = [_assignment_to_domain(o) for o in assign_rows]
    await store.seed(runs, assignments)
    rep.written = len(runs) + len(assignments)
    rep.validated = 0
    for r in runs:
        back = await store.get_run(r.id)
        if back is not None and back.model_dump() == r.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"clustering_run id={r.id}: readback != source")
    for a in assignments:
        back = await store.get_assignment(a.run_id, a.username)
        if back is not None and back.model_dump() == a.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"cluster_assignment id={a.id}: readback != source")
    return rep
