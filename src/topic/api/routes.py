"""主题管理 API 路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.async_session import get_db_session
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain
from src.topic.api.schemas import (
    AccountResponse,
    CreateSummaryTaskRequest,
    CreateTopicRequest,
    DefaultPromptResponse,
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


# ── 主题 CRUD ──

@router.post("", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
async def create_topic(
    request: CreateTopicRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    try:
        topic = await _topic_service.create_topic(session, request.name, request.description)
        return topic
    except ValueError as e:
        error_msg = str(e)
        if "已存在" in error_msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@router.get("", response_model=list[TopicListItem])
async def list_topics(
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    return await _topic_service.list_topics(session)


@router.get("/{topic_id}", response_model=TopicDetailResponse)
async def get_topic(
    topic_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    topic = await _topic_service.get_topic(session, topic_id)
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")
    return topic


@router.put("/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: int,
    request: UpdateTopicRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
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
    _admin: UserDomain = Depends(get_current_admin_user),
):
    result = await _topic_service.delete_topic(session, topic_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题不存在")


# ── 账号管理 ──

@router.put("/{topic_id}/accounts", response_model=list[AccountResponse])
async def set_accounts(
    topic_id: int,
    request: SetAccountsRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
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
    _admin: UserDomain = Depends(get_current_admin_user),
):
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
    _admin: UserDomain = Depends(get_current_admin_user),
):
    result = await _topic_service.remove_account(session, topic_id, username)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号未关联到该主题")


# ── 摘要任务 ──
# 注意：摘要任务路由需要匹配 /summary-tasks 前缀，但放在这个 router 中
# 路由路径需要避免与 /{topic_id} 冲突，所以放在单独的 router 中

summary_router = APIRouter(prefix="/api/topics/summary-tasks", tags=["topic-summaries"])


@summary_router.get("/default-prompt", response_model=DefaultPromptResponse)
async def get_default_prompt(
    _admin: UserDomain = Depends(get_current_admin_user),
):
    """返回默认的摘要系统提示词模板。"""
    from src.topic.services.topic_summary_service import DEFAULT_TOPIC_SUMMARY_PROMPT
    return DefaultPromptResponse(prompt=DEFAULT_TOPIC_SUMMARY_PROMPT)


@summary_router.post("", response_model=SummaryTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_summary_task(
    request: CreateSummaryTaskRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    """创建摘要任务并异步启动执行。"""
    # 延迟导入避免循环依赖
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
    _admin: UserDomain = Depends(get_current_admin_user),
):
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    return await service.list_tasks(session, topic_id)


@summary_router.get("/{task_id}", response_model=SummaryTaskDetailResponse)
async def get_summary_task(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    task = await service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摘要任务不存在")
    return task


@summary_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_summary_task(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    from src.topic.services.topic_summary_service import TopicSummaryService
    service = TopicSummaryService.get_instance()
    result = await service.delete_task(session, task_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="摘要任务不存在")
