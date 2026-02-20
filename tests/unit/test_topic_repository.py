"""TopicRepository 和 TopicSummaryTaskRepository 单元测试。

测试主题管理数据访问层的完整 CRUD 操作、约束验证和级联删除。
"""

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
)
from src.topic.infrastructure.repository import TopicRepository, TopicSummaryTaskRepository
from src.topic.domain.models import TopicSummaryTaskStatus


# ── Fixtures ──


@pytest.fixture
def topic_repo() -> TopicRepository:
    return TopicRepository()


@pytest.fixture
def task_repo() -> TopicSummaryTaskRepository:
    return TopicSummaryTaskRepository()


def _make_topic(name: str = "AI 热点", description: str | None = "人工智能相关话题") -> TopicOrm:
    return TopicOrm.from_domain(name=name, description=description)


def _make_account(topic_id: int, username: str) -> TopicAccountOrm:
    return TopicAccountOrm(topic_id=topic_id, username=username)


def _make_task(topic_id: int, **kwargs) -> TopicSummaryTaskOrm:
    defaults = {
        "topic_id": topic_id,
        "time_span_hours": 24,
        "deadline": datetime.now(timezone.utc) - timedelta(hours=24),
        "status": TopicSummaryTaskStatus.pending.value,
    }
    defaults.update(kwargs)
    return TopicSummaryTaskOrm(**defaults)


def _make_summary(task_id: int, **kwargs) -> TopicSummaryOrm:
    defaults = {
        "task_id": task_id,
        "content": "这是一段摘要内容。",
        "llm_provider": "openai",
        "llm_model": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "cost_usd": 0.005,
        "tweet_count": 10,
        "account_count": 3,
    }
    defaults.update(kwargs)
    return TopicSummaryOrm(**defaults)


# ── 主题 CRUD 测试 ──


@pytest.mark.asyncio
async def test_create_topic(async_session, topic_repo):
    """创建主题并验证字段。"""
    topic = _make_topic()
    created = await topic_repo.create(async_session, topic)

    assert created.id is not None
    assert created.name == "AI 热点"
    assert created.description == "人工智能相关话题"
    assert created.created_at is not None
    assert created.updated_at is not None


@pytest.mark.asyncio
async def test_get_by_id(async_session, topic_repo):
    """按 ID 查询主题。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.commit()

    found = await topic_repo.get_by_id(async_session, topic.id)
    assert found is not None
    assert found.id == topic.id
    assert found.name == "AI 热点"


@pytest.mark.asyncio
async def test_get_by_id_not_found(async_session, topic_repo):
    """按不存在的 ID 查询返回 None。"""
    found = await topic_repo.get_by_id(async_session, 9999)
    assert found is None


@pytest.mark.asyncio
async def test_get_by_name(async_session, topic_repo):
    """按名称查询主题。"""
    topic = _make_topic(name="区块链")
    await topic_repo.create(async_session, topic)
    await async_session.commit()

    found = await topic_repo.get_by_name(async_session, "区块链")
    assert found is not None
    assert found.name == "区块链"


@pytest.mark.asyncio
async def test_get_by_name_not_found(async_session, topic_repo):
    """按不存在的名称查询返回 None。"""
    found = await topic_repo.get_by_name(async_session, "不存在的主题")
    assert found is None


@pytest.mark.asyncio
async def test_list_all(async_session, topic_repo):
    """列出所有主题，按创建时间倒序。"""
    t1 = _make_topic(name="主题A")
    t2 = _make_topic(name="主题B")
    await topic_repo.create(async_session, t1)
    await topic_repo.create(async_session, t2)
    await async_session.commit()

    topics = await topic_repo.list_all(async_session)
    assert len(topics) == 2
    # 按创建时间倒序，后创建的排前面
    names = [t[0].name for t in topics]
    assert names == ["主题B", "主题A"]


@pytest.mark.asyncio
async def test_list_all_with_account_count(async_session, topic_repo):
    """list_all 返回正确的账号数量。"""
    topic = _make_topic(name="测试主题")
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    # 添加 3 个账号
    for username in ["user1", "user2", "user3"]:
        account = _make_account(topic.id, username)
        await topic_repo.add_account(async_session, account)
    await async_session.commit()

    topics = await topic_repo.list_all(async_session)
    assert len(topics) == 1
    assert topics[0][1] == 3  # account_count == 3


@pytest.mark.asyncio
async def test_list_all_empty(async_session, topic_repo):
    """空数据库返回空列表。"""
    topics = await topic_repo.list_all(async_session)
    assert topics == []


@pytest.mark.asyncio
async def test_update_topic(async_session, topic_repo):
    """更新主题字段。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.commit()

    topic.name = "AI 热点（更新）"
    topic.description = "更新后的描述"
    await topic_repo.update(async_session, topic)
    await async_session.commit()

    found = await topic_repo.get_by_id(async_session, topic.id)
    assert found.name == "AI 热点（更新）"
    assert found.description == "更新后的描述"


@pytest.mark.asyncio
async def test_delete_topic(async_session, topic_repo):
    """删除主题。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.commit()

    deleted = await topic_repo.delete(async_session, topic.id)
    assert deleted is True
    await async_session.commit()

    found = await topic_repo.get_by_id(async_session, topic.id)
    assert found is None


@pytest.mark.asyncio
async def test_delete_topic_not_found(async_session, topic_repo):
    """删除不存在的主题返回 False。"""
    deleted = await topic_repo.delete(async_session, 9999)
    assert deleted is False


# ── 唯一约束测试 ──


@pytest.mark.asyncio
async def test_unique_topic_name(async_session, topic_repo):
    """同一 user_id 下主题名称唯一：相同 (user_id, name) 报 IntegrityError。"""
    t1 = _make_topic(name="相同名称")
    t1.user_id = 1
    await topic_repo.create(async_session, t1)
    await async_session.commit()

    t2 = _make_topic(name="相同名称")
    t2.user_id = 1
    with pytest.raises(IntegrityError):
        await topic_repo.create(async_session, t2)
        await async_session.flush()


# ── 账号管理测试 ──


@pytest.mark.asyncio
async def test_add_account(async_session, topic_repo):
    """添加账号到主题。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    account = _make_account(topic.id, "elonmusk")
    created = await topic_repo.add_account(async_session, account)
    assert created.id is not None
    assert created.username == "elonmusk"
    assert created.topic_id == topic.id


@pytest.mark.asyncio
async def test_get_account(async_session, topic_repo):
    """查询主题下的账号。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    account = _make_account(topic.id, "openai")
    await topic_repo.add_account(async_session, account)
    await async_session.commit()

    found = await topic_repo.get_account(async_session, topic.id, "openai")
    assert found is not None
    assert found.username == "openai"


@pytest.mark.asyncio
async def test_get_accounts(async_session, topic_repo):
    """获取主题下所有账号。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    for name in ["user_a", "user_b"]:
        await topic_repo.add_account(async_session, _make_account(topic.id, name))
    await async_session.commit()

    accounts = await topic_repo.get_accounts(async_session, topic.id)
    assert len(accounts) == 2
    usernames = {a.username for a in accounts}
    assert usernames == {"user_a", "user_b"}


@pytest.mark.asyncio
async def test_delete_account(async_session, topic_repo):
    """删除主题下的账号。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    await topic_repo.add_account(async_session, _make_account(topic.id, "to_delete"))
    await async_session.commit()

    deleted = await topic_repo.delete_account(async_session, topic.id, "to_delete")
    assert deleted is True

    found = await topic_repo.get_account(async_session, topic.id, "to_delete")
    assert found is None


@pytest.mark.asyncio
async def test_delete_account_not_found(async_session, topic_repo):
    """删除不存在的账号返回 False。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    deleted = await topic_repo.delete_account(async_session, topic.id, "not_exist")
    assert deleted is False


@pytest.mark.asyncio
async def test_unique_account_per_topic(async_session, topic_repo):
    """同一主题下同一 username 的唯一约束。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    await topic_repo.add_account(async_session, _make_account(topic.id, "duplicate"))
    await async_session.commit()

    with pytest.raises(IntegrityError):
        await topic_repo.add_account(async_session, _make_account(topic.id, "duplicate"))
        await async_session.flush()


@pytest.mark.asyncio
async def test_replace_accounts(async_session, topic_repo):
    """替换主题的所有账号。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    # 先添加旧账号
    for name in ["old_a", "old_b"]:
        await topic_repo.add_account(async_session, _make_account(topic.id, name))
    await async_session.commit()

    # 用新账号替换
    new_accounts = [_make_account(topic.id, name) for name in ["new_x", "new_y", "new_z"]]
    result = await topic_repo.replace_accounts(async_session, topic.id, new_accounts)
    await async_session.commit()

    assert len(result) == 3

    # 验证旧账号已被删除，新账号已添加
    accounts = await topic_repo.get_accounts(async_session, topic.id)
    usernames = {a.username for a in accounts}
    assert usernames == {"new_x", "new_y", "new_z"}


# ── 级联删除测试 ──


@pytest.mark.asyncio
async def test_cascade_delete_accounts(async_session, topic_repo):
    """删除主题后，关联的账号也被级联删除。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    await topic_repo.add_account(async_session, _make_account(topic.id, "cascaded"))
    await async_session.commit()

    topic_id = topic.id
    await topic_repo.delete(async_session, topic_id)
    await async_session.commit()

    accounts = await topic_repo.get_accounts(async_session, topic_id)
    assert accounts == []


@pytest.mark.asyncio
async def test_cascade_delete_tasks_and_summaries(async_session, topic_repo, task_repo):
    """删除主题后，关联的任务和摘要也被级联删除。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.flush()

    summary = _make_summary(task.id)
    await task_repo.create_summary(async_session, summary)
    await async_session.commit()

    task_id = task.id
    topic_id = topic.id

    # 删除主题
    await topic_repo.delete(async_session, topic_id)
    await async_session.commit()

    # 清除 session 缓存，确保后续查询从数据库重新加载
    async_session.expire_all()

    # 任务和摘要都应被删除（ORM cascade="all, delete-orphan"）
    found_task = await task_repo.get_task(async_session, task_id)
    assert found_task is None

    found_summary = await task_repo.get_summary_by_task(async_session, task_id)
    assert found_summary is None


# ── 摘要任务 CRUD 测试 ──


@pytest.mark.asyncio
async def test_create_task(async_session, topic_repo, task_repo):
    """创建摘要任务。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id, custom_prompt="自定义提示词")
    created = await task_repo.create_task(async_session, task)
    await async_session.commit()

    assert created.id is not None
    assert created.topic_id == topic.id
    assert created.time_span_hours == 24
    assert created.status == TopicSummaryTaskStatus.pending.value
    assert created.custom_prompt == "自定义提示词"


@pytest.mark.asyncio
async def test_get_task_with_topic_name(async_session, topic_repo, task_repo):
    """获取任务时关联加载 topic_name。"""
    topic = _make_topic(name="区块链动态")
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.commit()

    found = await task_repo.get_task(async_session, task.id)
    assert found is not None
    # 通过 selectinload 加载了 topic 关系
    assert found.topic is not None
    assert found.topic.name == "区块链动态"

    # 测试 to_domain 中 topic_name 的传递
    domain = found.to_domain()
    assert domain.topic_name == "区块链动态"


@pytest.mark.asyncio
async def test_get_task_with_summary(async_session, topic_repo, task_repo):
    """获取任务时关联加载 summary。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.flush()

    summary = _make_summary(task.id, content="摘要内容测试")
    await task_repo.create_summary(async_session, summary)
    await async_session.commit()

    found = await task_repo.get_task(async_session, task.id)
    assert found is not None
    assert found.summary is not None
    assert found.summary.content == "摘要内容测试"

    domain = found.to_domain()
    assert domain.summary is not None
    assert domain.summary.content == "摘要内容测试"


@pytest.mark.asyncio
async def test_get_task_not_found(async_session, task_repo):
    """获取不存在的任务返回 None。"""
    found = await task_repo.get_task(async_session, 9999)
    assert found is None


@pytest.mark.asyncio
async def test_list_tasks_all(async_session, topic_repo, task_repo):
    """列出所有任务。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    for _ in range(3):
        await task_repo.create_task(async_session, _make_task(topic.id))
    await async_session.commit()

    tasks = await task_repo.list_tasks(async_session)
    assert len(tasks) == 3


@pytest.mark.asyncio
async def test_list_tasks_filter_by_topic(async_session, topic_repo, task_repo):
    """按 topic_id 筛选任务。"""
    t1 = _make_topic(name="主题1")
    t2 = _make_topic(name="主题2")
    await topic_repo.create(async_session, t1)
    await topic_repo.create(async_session, t2)
    await async_session.flush()

    # 主题1 有 2 个任务，主题2 有 1 个任务
    await task_repo.create_task(async_session, _make_task(t1.id))
    await task_repo.create_task(async_session, _make_task(t1.id))
    await task_repo.create_task(async_session, _make_task(t2.id))
    await async_session.commit()

    tasks_t1 = await task_repo.list_tasks(async_session, topic_id=t1.id)
    assert len(tasks_t1) == 2
    for t in tasks_t1:
        assert t.topic_id == t1.id

    tasks_t2 = await task_repo.list_tasks(async_session, topic_id=t2.id)
    assert len(tasks_t2) == 1
    assert tasks_t2[0].topic_id == t2.id


@pytest.mark.asyncio
async def test_update_task(async_session, topic_repo, task_repo):
    """更新任务状态。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.commit()

    task.status = TopicSummaryTaskStatus.running.value
    task.started_at = datetime.now(timezone.utc)
    await task_repo.update_task(async_session, task)
    await async_session.commit()

    found = await task_repo.get_task(async_session, task.id)
    assert found.status == TopicSummaryTaskStatus.running.value
    assert found.started_at is not None


@pytest.mark.asyncio
async def test_delete_task(async_session, topic_repo, task_repo):
    """删除任务。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.commit()

    deleted = await task_repo.delete_task(async_session, task.id)
    assert deleted is True

    found = await task_repo.get_task(async_session, task.id)
    assert found is None


@pytest.mark.asyncio
async def test_delete_task_not_found(async_session, task_repo):
    """删除不存在的任务返回 False。"""
    deleted = await task_repo.delete_task(async_session, 9999)
    assert deleted is False


# ── 摘要 CRUD 测试 ──


@pytest.mark.asyncio
async def test_create_summary(async_session, topic_repo, task_repo):
    """创建摘要结果。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.flush()

    summary = _make_summary(task.id)
    created = await task_repo.create_summary(async_session, summary)
    await async_session.commit()

    assert created.id is not None
    assert created.task_id == task.id
    assert created.llm_provider == "openai"


@pytest.mark.asyncio
async def test_get_summary_by_task(async_session, topic_repo, task_repo):
    """按 task_id 查询摘要。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.flush()

    summary = _make_summary(task.id)
    await task_repo.create_summary(async_session, summary)
    await async_session.commit()

    found = await task_repo.get_summary_by_task(async_session, task.id)
    assert found is not None
    assert found.task_id == task.id


@pytest.mark.asyncio
async def test_get_summary_by_task_not_found(async_session, task_repo):
    """查询不存在的摘要返回 None。"""
    found = await task_repo.get_summary_by_task(async_session, 9999)
    assert found is None


# ── to_domain 转换测试 ──


@pytest.mark.asyncio
async def test_topic_to_domain(async_session, topic_repo):
    """TopicOrm.to_domain() 正确转换。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.commit()

    found = await topic_repo.get_by_id(async_session, topic.id)
    domain = found.to_domain()
    assert domain.id == found.id
    assert domain.name == "AI 热点"
    assert domain.description == "人工智能相关话题"


@pytest.mark.asyncio
async def test_topic_to_domain_with_count(async_session, topic_repo):
    """TopicOrm.to_domain_with_count() 正确转换。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    await topic_repo.add_account(async_session, _make_account(topic.id, "user1"))
    await async_session.commit()

    found = await topic_repo.get_by_id(async_session, topic.id)
    domain = found.to_domain_with_count(account_count=1)
    assert domain.account_count == 1


@pytest.mark.asyncio
async def test_topic_to_detail_domain(async_session, topic_repo):
    """TopicOrm.to_detail_domain() 正确转换（含账号列表）。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    await topic_repo.add_account(async_session, _make_account(topic.id, "detail_user"))
    await async_session.commit()

    found = await topic_repo.get_by_id(async_session, topic.id)
    domain = found.to_detail_domain()
    assert len(domain.accounts) == 1
    assert domain.accounts[0].username == "detail_user"


@pytest.mark.asyncio
async def test_get_latest_completed_task(async_session, topic_repo, task_repo):
    """获取主题最新的已完成摘要任务。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    now = datetime.now(timezone.utc)

    # 创建较早的已完成任务
    old_task = _make_task(
        topic.id,
        status=TopicSummaryTaskStatus.completed.value,
        completed_at=now - timedelta(hours=2),
    )
    await task_repo.create_task(async_session, old_task)
    await async_session.flush()
    old_summary = _make_summary(old_task.id, content="旧摘要")
    await task_repo.create_summary(async_session, old_summary)

    # 创建较新的已完成任务
    new_task = _make_task(
        topic.id,
        status=TopicSummaryTaskStatus.completed.value,
        completed_at=now,
    )
    await task_repo.create_task(async_session, new_task)
    await async_session.flush()
    new_summary = _make_summary(new_task.id, content="新摘要")
    await task_repo.create_summary(async_session, new_summary)

    # 创建一个 pending 任务（不应被返回）
    pending_task = _make_task(topic.id, status=TopicSummaryTaskStatus.pending.value)
    await task_repo.create_task(async_session, pending_task)
    await async_session.commit()

    found = await task_repo.get_latest_completed_task(async_session, topic.id)
    assert found is not None
    assert found.id == new_task.id
    assert found.summary is not None
    assert found.summary.content == "新摘要"
    assert found.topic is not None
    assert found.topic.name == topic.name


@pytest.mark.asyncio
async def test_get_latest_completed_task_none(async_session, topic_repo, task_repo):
    """无已完成任务时返回 None。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    # 只有 pending 任务
    pending_task = _make_task(topic.id, status=TopicSummaryTaskStatus.pending.value)
    await task_repo.create_task(async_session, pending_task)
    await async_session.commit()

    found = await task_repo.get_latest_completed_task(async_session, topic.id)
    assert found is None


@pytest.mark.asyncio
async def test_summary_to_domain(async_session, topic_repo, task_repo):
    """TopicSummaryOrm.to_domain() 正确转换。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task = _make_task(topic.id)
    await task_repo.create_task(async_session, task)
    await async_session.flush()

    summary = _make_summary(task.id, content="转换测试", cost_usd=0.01)
    await task_repo.create_summary(async_session, summary)
    await async_session.commit()

    found = await task_repo.get_summary_by_task(async_session, task.id)
    domain = found.to_domain()
    assert domain.content == "转换测试"
    assert domain.cost_usd == 0.01
    assert domain.llm_provider == "openai"
    assert domain.llm_model == "gpt-4o"
