"""Analytics API 路由。

包含聚类分析（admin）和发文频次分析（用户级别）两组端点。
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.api.schemas import (
    AccountDistributionResponse,
    ClusterAssignmentResponse,
    ClusteringRunDetailResponse,
    ClusteringRunSummaryResponse,
    DistributionsResponse,
    FrequencySlotResponse,
    MoveAccountRequest,
    PostingFrequencyResponse,
    ReCutRequest,
    RunClusteringRequest,
    TimeRangeResponse,
)
from src.analytics.services.analytics_service import AnalyticsService
from src.analytics.services.clustering_service import ClusteringService
from src.database.async_session import get_db_session
from src.topic.infrastructure.models import TopicOrm
from src.user.api.auth import get_current_admin_user, get_current_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/analytics", tags=["analytics"])

_clustering_service = ClusteringService()


def _run_to_detail(run) -> ClusteringRunDetailResponse:
    """将 ORM 运行对象转换为详情响应。"""
    linkage_matrix = None
    if run.linkage_matrix_json:
        linkage_matrix = json.loads(run.linkage_matrix_json)
    account_labels = None
    if run.account_labels_json:
        account_labels = json.loads(run.account_labels_json)

    assignments = []
    for a in run.assignments:
        assignments.append(
            ClusterAssignmentResponse(
                id=a.id,
                username=a.username,
                cluster_id=a.cluster_id,
                hourly_distribution=json.loads(a.hourly_distribution_json),
                tweet_count=a.tweet_count,
                is_manual_override=a.is_manual_override,
            )
        )

    return ClusteringRunDetailResponse(
        id=run.id,
        status=run.status,
        cut_height=run.cut_height,
        num_clusters=run.num_clusters,
        num_accounts=run.num_accounts,
        num_excluded=run.num_excluded,
        min_tweets_threshold=run.min_tweets_threshold,
        linkage_method=run.linkage_method,
        error_message=run.error_message,
        created_at=run.created_at,
        completed_at=run.completed_at,
        linkage_matrix=linkage_matrix,
        account_labels=account_labels,
        assignments=assignments,
    )


def _run_to_summary(run) -> ClusteringRunSummaryResponse:
    """将 ORM 运行对象转换为摘要响应。"""
    return ClusteringRunSummaryResponse(
        id=run.id,
        status=run.status,
        num_clusters=run.num_clusters,
        num_accounts=run.num_accounts,
        num_excluded=run.num_excluded,
        min_tweets_threshold=run.min_tweets_threshold,
        linkage_method=run.linkage_method,
        error_message=run.error_message,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("/distributions", response_model=DistributionsResponse)
async def get_distributions(
    min_tweets: int = 20,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """预览所有账号的 24 维分布向量。"""
    distributions, excluded = await _clustering_service.get_distributions(
        session, min_tweets=min_tweets
    )
    return DistributionsResponse(
        distributions=[
            AccountDistributionResponse(
                username=d.username,
                distribution=d.distribution,
                tweet_count=d.tweet_count,
            )
            for d in distributions
        ],
        excluded=excluded,
    )


@router.post("/clustering", response_model=ClusteringRunDetailResponse, status_code=status.HTTP_201_CREATED)
async def run_clustering(
    request: RunClusteringRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """触发一次聚类分析。"""
    params = request or RunClusteringRequest()
    try:
        run = await _clustering_service.run_clustering(
            session,
            min_tweets=params.min_tweets,
            linkage_method=params.linkage_method,
            cut_height=params.cut_height,
            num_clusters=params.num_clusters,
        )
        return _run_to_detail(run)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/clustering", response_model=list[ClusteringRunSummaryResponse])
async def list_clustering_runs(
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """列出所有聚类运行记录。"""
    runs = await _clustering_service.list_runs(session)
    return [_run_to_summary(r) for r in runs]


@router.get("/clustering/latest", response_model=ClusteringRunDetailResponse)
async def get_latest_clustering(
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """获取最近一次完成的聚类运行。"""
    run = await _clustering_service.get_latest_completed(session)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="暂无已完成的聚类运行")
    return _run_to_detail(run)


@router.get("/clustering/{run_id}", response_model=ClusteringRunDetailResponse)
async def get_clustering_run(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """获取指定运行的完整详情。"""
    run = await _clustering_service.get_run(session, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="聚类运行不存在")
    return _run_to_detail(run)


@router.post("/clustering/{run_id}/re-cut", response_model=ClusteringRunDetailResponse)
async def recut_clustering(
    run_id: int,
    request: ReCutRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """重切割树状图。"""
    try:
        run = await _clustering_service.recut(
            session,
            run_id,
            cut_height=request.cut_height,
            num_clusters=request.num_clusters,
        )
        return _run_to_detail(run)
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.put(
    "/clustering/{run_id}/assignments/{username}",
    response_model=ClusterAssignmentResponse,
)
async def move_account(
    run_id: int,
    username: str,
    request: MoveAccountRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """手动移动账号到其他聚类组。"""
    try:
        assignment = await _clustering_service.move_account(
            session, run_id, username, request.cluster_id
        )
        return ClusterAssignmentResponse(
            id=assignment.id,
            username=assignment.username,
            cluster_id=assignment.cluster_id,
            hourly_distribution=json.loads(assignment.hourly_distribution_json),
            tweet_count=assignment.tweet_count,
            is_manual_override=assignment.is_manual_override,
        )
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.delete("/clustering/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_clustering_run(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_admin_user),  # noqa: ARG001
):
    """删除一次聚类运行。"""
    result = await _clustering_service.delete_run(session, run_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="聚类运行不存在")


# ── 发文频次分析路由（用户级别，非 admin-only） ──────────────────────

analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@analytics_router.get(
    "/topics/{topic_id}/posting-frequency",
    response_model=PostingFrequencyResponse,
)
async def get_posting_frequency(
    topic_id: int,
    tz_offset: int = Query(default=0),
    slots: int = Query(default=50, ge=1, le=336),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    """获取主题下所有关联账号的发文频次分布。"""
    # 1. 查询主题
    result = await session.execute(
        select(TopicOrm).where(TopicOrm.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在"
        )

    # 2. 所有权检查：admin 可访问所有，非 admin 只能访问自己的主题
    if not current_user.is_admin and topic.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该主题"
        )

    # 3. 调用 Service 获取数据
    service = AnalyticsService(session)
    data = await service.get_posting_frequency(
        topic_id=topic_id, tz_offset=tz_offset, slots=slots
    )

    # 4. 包装响应
    return PostingFrequencyResponse(
        topic_id=topic_id,
        topic_name=topic.name,
        slot_minutes=30,
        slots=slots,
        tz_offset=tz_offset,
        time_range=TimeRangeResponse(
            start=data["time_range_start"].isoformat(),
            end=data["time_range_end"].isoformat(),
        ),
        distribution=[
            FrequencySlotResponse(slot=d["slot"], count=d["count"])
            for d in data["distribution"]
        ],
        total_tweets=data["total_tweets"],
    )
