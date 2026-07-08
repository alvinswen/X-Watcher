"""摘要 API 路由。

仅保留历史摘要读取端点。摘要生成由 Agent 回写通道承担。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.data_layer.provider import get_summary_repo
from src.summarization.api.schemas import ErrorResponse, SummaryResponse
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summaries", tags=["summaries"])


@router.get(
    "/tweets/{tweet_id}",
    response_model=SummaryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "摘要不存在"},
        500: {"model": ErrorResponse, "description": "服务器错误"},
    },
)
async def get_tweet_summary(
    tweet_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> SummaryResponse:
    """查询单条推文的摘要。"""
    try:
        repository = get_summary_repo()
        summary = await repository.get_summary_by_tweet(tweet_id)

        if summary is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"推文摘要不存在: {tweet_id}",
            )

        return SummaryResponse.from_domain(summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("查询推文摘要失败 (tweet_id=%s): %s", tweet_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
