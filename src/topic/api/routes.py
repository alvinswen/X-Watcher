"""主题管理 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_db_session
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain
from src.topic.api.schemas import (
    AccountResponse,
    CreateSummaryTaskRequest,
    CreateTopicRequest,
    DefaultPromptResponse,
    ImagePromptResponse,
    LatestSummaryResponse,
    SetAccountsRequest,
    SummaryTaskDetailResponse,
    SummaryTaskResponse,
    TopicDetailResponse,
    TopicListItem,
    TopicResponse,
    UpdateTopicRequest,
)
from src.topic.services.topic_service import TopicService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topics", tags=["topics"])

_topic_service = TopicService()


async def _check_topic_ownership(topic, current_user: UserDomain):
    """检查主题所有权。admin 可访问所有主题，非 admin 只能访问自己的。"""
    if not current_user.is_admin and topic.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该主题")


# ── 主题 CRUD ──

@router.post("", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
async def create_topic(
    request: CreateTopicRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    try:
        topic = await _topic_service.create_topic(
            session, request.name, request.description, user_id=current_user.id
        )
        return topic
    except ValueError as e:
        error_msg = str(e)
        if "已存在" in error_msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.get("", response_model=list[TopicListItem])
async def list_topics(
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    user_id = None if current_user.is_admin else current_user.id
    return await _topic_service.list_topics(session, user_id=user_id)


@router.get("/{topic_id}/latest-summary", response_model=LatestSummaryResponse)
async def get_latest_summary(
    topic_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    """获取主题的最新摘要（快捷接口）。"""
    # 所有权检查
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic, current_user)

    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    try:
        task = await service.get_latest_summary(session, topic_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if not task or not task.summary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该主题暂无已完成的摘要")
    return LatestSummaryResponse(
        topic_id=task.topic_id,
        topic_name=task.topic_name,
        content=task.summary.content,
        generated_at=task.completed_at,
        time_span_hours=task.time_span_hours,
        deadline=task.deadline,
        tweet_count=task.summary.tweet_count,
        account_count=task.summary.account_count,
        task_id=task.id,
    )


@router.get("/{topic_id}", response_model=TopicDetailResponse)
async def get_topic(
    topic_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic, current_user)
    return topic


@router.put("/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: int,
    request: UpdateTopicRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    # 先检查所有权
    topic_detail = await _topic_service.get_topic(session, topic_id)
    if not topic_detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic_detail, current_user)

    try:
        topic = await _topic_service.update_topic(session, topic_id, request.name, request.description)
        if not topic:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
        return topic
    except ValueError as e:
        error_msg = str(e)
        if "已存在" in error_msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(
    topic_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    # 先检查所有权
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic, current_user)

    result = await _topic_service.delete_topic(session, topic_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")


# ── 账号管理 ──

@router.put("/{topic_id}/accounts", response_model=list[AccountResponse])
async def set_accounts(
    topic_id: int,
    request: SetAccountsRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    # 先检查所有权
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic, current_user)

    try:
        accounts = await _topic_service.set_accounts(session, topic_id, request.usernames)
        return accounts
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg and "主题" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.post("/{topic_id}/accounts/{username}", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def add_account(
    topic_id: int,
    username: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    # 先检查所有权
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic, current_user)

    try:
        account = await _topic_service.add_account(session, topic_id, username)
        return account
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg and "主题" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        if "已关联" in error_msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.delete("/{topic_id}/accounts/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_account(
    topic_id: int,
    username: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    # 先检查所有权
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    await _check_topic_ownership(topic, current_user)

    result = await _topic_service.remove_account(session, topic_id, username)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号未关联到该主题")


# ── 摘要任务 ──
# 注意：摘要任务路由需要匹配 /summary-tasks 前缀，但放在这个 router 中
# 路由路径需要避免与 /{topic_id} 冲突，所以放在单独的 router 中

summary_router = APIRouter(prefix="/api/topics/summary-tasks", tags=["topic-summaries"])


@summary_router.get("/default-prompt", response_model=DefaultPromptResponse)
async def get_default_prompt(
    _user: UserDomain = Depends(get_current_user),
):
    """返回默认的摘要系统提示词模板。"""
    from src.topic.services.topic_summary_service import DEFAULT_TOPIC_SUMMARY_PROMPT
    return DefaultPromptResponse(prompt=DEFAULT_TOPIC_SUMMARY_PROMPT)


@summary_router.post("", response_model=SummaryTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_summary_task(
    request: CreateSummaryTaskRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    """创建摘要任务并异步启动执行。"""
    # 检查 topic 所有权
    topic = await _topic_service.get_topic(session, request.topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"主题 ID {request.topic_id} 不存在")
    await _check_topic_ownership(topic, current_user)

    from src.topic.services.topic_summary_service import TopicSummaryService
    from src.database.async_session import get_async_session_maker

    try:
        service = TopicSummaryService.get_instance()
        session_factory = get_async_session_maker()
        task = await service.create_and_execute_task(
            session=session,
            session_factory=session_factory,
            topic_id=request.topic_id,
            time_span_hours=request.time_span_hours,
            deadline=request.deadline,
            custom_prompt=request.custom_prompt,
            tz_offset=request.tz_offset,
        )
        return task
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@summary_router.get("", response_model=list[SummaryTaskResponse])
async def list_summary_tasks(
    topic_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    user_id = None if current_user.is_admin else current_user.id
    return await service.list_tasks(session, topic_id, user_id=user_id)


@summary_router.get("/{task_id}", response_model=SummaryTaskDetailResponse)
async def get_summary_task(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    task = await service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摘要任务不存在")
    # 通过 task→topic 检查所有权
    topic = await _topic_service.get_topic(session, task.topic_id)
    if topic:
        await _check_topic_ownership(topic, current_user)
    return task


@summary_router.post("/{task_id}/generate-image-prompt", response_model=ImagePromptResponse)
async def generate_image_prompt(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    """基于摘要内容实时生成配图提示词。"""
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    # 通过 task→topic 检查所有权
    task = await service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摘要任务不存在")
    topic = await _topic_service.get_topic(session, task.topic_id)
    if topic:
        await _check_topic_ownership(topic, current_user)

    try:
        return await service.generate_image_prompt(session, task_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@summary_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_summary_task(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserDomain = Depends(get_current_user),
):
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    # 通过 task→topic 检查所有权
    task = await service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摘要任务不存在")
    topic = await _topic_service.get_topic(session, task.topic_id)
    if topic:
        await _check_topic_ownership(topic, current_user)

    result = await service.delete_task(session, task_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摘要任务不存在")
