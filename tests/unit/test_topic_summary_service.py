"""TopicSummaryService 单元测试。

测试主题摘要任务执行服务的核心逻辑：
- estimate_tokens 估算
- _build_prompt 按作者分组和模板填充
- _build_prompt token 截断
- _call_llm_with_failover failover 逻辑
- create_and_execute_task 完整流程
- 边界场景（无推文、无账号、主题不存在等）
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from returns.result import Failure, Success

from src.summarization.domain.models import LLMResponse
from src.topic.domain.models import TopicSummaryTaskStatus
from src.topic.infrastructure.models import (
    TopicAccountOrm,
    TopicOrm,
    TopicSummaryOrm,
    TopicSummaryTaskOrm,
)
from src.topic.infrastructure.repository import TopicRepository, TopicSummaryTaskRepository
from src.topic.services.topic_summary_service import (
    DEFAULT_TOPIC_SUMMARY_PROMPT,
    MAX_CONTEXT_TOKENS,
    TopicSummaryService,
    build_llm_providers,
    estimate_tokens,
)


# ── Fixtures ──


@pytest.fixture
def topic_repo() -> TopicRepository:
    return TopicRepository()


@pytest.fixture
def task_repo() -> TopicSummaryTaskRepository:
    return TopicSummaryTaskRepository()


def _make_topic(name: str = "AI 热点", description: str | None = "测试主题") -> TopicOrm:
    return TopicOrm.from_domain(name=name, description=description)


def _make_account(topic_id: int, username: str) -> TopicAccountOrm:
    return TopicAccountOrm(topic_id=topic_id, username=username)


def _make_llm_response(**kwargs) -> LLMResponse:
    defaults = {
        "content": "这是LLM生成的摘要报告。",
        "model": "test-model",
        "provider": "openrouter",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "cost_usd": 0.005,
        "finish_reason": "stop",
    }
    defaults.update(kwargs)
    return LLMResponse(**defaults)


def _make_mock_provider(name: str = "mock_provider", succeed: bool = True, response: LLMResponse | None = None):
    """创建 mock LLM provider。"""
    provider = AsyncMock()
    provider.get_provider_name.return_value = name
    provider.get_model_name.return_value = "mock-model"
    if succeed:
        resp = response or _make_llm_response(provider=name if name in ("openrouter", "minimax") else "openrouter")
        provider.complete.return_value = Success(resp)
    else:
        provider.complete.return_value = Failure(Exception("Provider error"))
    return provider


# ── estimate_tokens 测试 ──


def test_estimate_tokens_pure_chinese():
    """纯中文：每个汉字 ≈ 1 token。"""
    assert estimate_tokens("你好世界") == 4


def test_estimate_tokens_pure_english():
    """纯英文：每个词 ≈ 1.3 token。"""
    result = estimate_tokens("hello world")
    # "hello world" = 2 words * 1.3 = 2.6 → int(2.6) = 2
    assert result == 2


def test_estimate_tokens_mixed():
    """中英混合文本。"""
    result = estimate_tokens("你好 hello world 世界")
    # 2 中文字 + 英文部分含词汇
    assert result > 2


def test_estimate_tokens_empty():
    """空字符串。"""
    assert estimate_tokens("") == 0


# ── build_llm_providers 测试 ──


def test_build_llm_providers_with_openrouter():
    """有 OpenRouter 环境变量时构建 provider。"""
    env = {
        "OPENROUTER_API_KEY": "test-key",
        "OPENROUTER_BASE_URL": "https://api.test.com/v1",
        "OPENROUTER_MODEL": "test-model",
    }
    with patch.dict("os.environ", env, clear=False):
        # 清除其他 provider 的环境变量
        with patch.dict("os.environ", {"MINIMAX_API_KEY": ""}, clear=False):
            providers = build_llm_providers()
            assert len(providers) >= 1


def test_build_llm_providers_empty():
    """无环境变量时返回空列表。"""
    env_clear = {
        "OPENROUTER_API_KEY": "",
        "MINIMAX_API_KEY": "",
        "OPEN_SOURCE_BASE_URL": "",
        "OPEN_SOURCE_MODEL": "",
    }
    with patch.dict("os.environ", env_clear, clear=False):
        providers = build_llm_providers()
        assert providers == []


# ── _build_prompt 测试 ──


def test_build_prompt_groups_by_author():
    """按作者分组、填充模板变量。"""
    service = TopicSummaryService(providers=[])
    tweets = [
        {"tweet_id": "1", "text": "Hello from A", "author": "user_a", "created_at": "2025-01-01 10:00", "translation": None},
        {"tweet_id": "2", "text": "Hello from B", "author": "user_b", "created_at": "2025-01-01 11:00", "translation": None},
        {"tweet_id": "3", "text": "Second from A", "author": "user_a", "created_at": "2025-01-01 12:00", "translation": None},
    ]
    prompt, count = service._build_prompt(tweets, ["user_a", "user_b"], 24)

    assert "@user_a" in prompt
    assert "@user_b" in prompt
    assert count == 3
    assert "1 天" in prompt
    assert "3 条推文" in prompt or str(count) in prompt


def test_build_prompt_prefers_translation():
    """优先使用已有翻译。"""
    service = TopicSummaryService(providers=[])
    tweets = [
        {"tweet_id": "1", "text": "Original English", "author": "user_a", "created_at": "2025-01-01", "translation": "已有中文翻译"},
    ]
    prompt, count = service._build_prompt(tweets, ["user_a"], 24)

    assert "已有中文翻译" in prompt
    assert "Original English" not in prompt
    assert count == 1


def test_build_prompt_time_span_hours():
    """时间跨度小于 24 小时用小时表示。"""
    service = TopicSummaryService(providers=[])
    tweets = [
        {"tweet_id": "1", "text": "Test", "author": "user_a", "created_at": "2025-01-01", "translation": None},
    ]
    prompt, _ = service._build_prompt(tweets, ["user_a"], 12)

    assert "12 小时" in prompt


def test_build_prompt_time_span_days_and_hours():
    """时间跨度超过 24 小时含余数时显示天和小时。"""
    service = TopicSummaryService(providers=[])
    tweets = [
        {"tweet_id": "1", "text": "Test", "author": "user_a", "created_at": "2025-01-01", "translation": None},
    ]
    prompt, _ = service._build_prompt(tweets, ["user_a"], 30)

    assert "1 天" in prompt
    assert "6 小时" in prompt


def test_build_prompt_custom_prompt():
    """使用自定义提示词模板。"""
    service = TopicSummaryService(providers=[])
    tweets = [
        {"tweet_id": "1", "text": "Test", "author": "user_a", "created_at": "2025-01-01", "translation": None},
    ]
    custom = "自定义模板: {account_count} 个账号, {time_span}, {tweet_count} 条推文\n{tweets_content}"
    prompt, count = service._build_prompt(tweets, ["user_a"], 24, custom_prompt=custom)

    assert "自定义模板" in prompt
    assert "1 个账号" in prompt
    assert count == 1


def test_build_prompt_token_truncation():
    """超过 MAX_CONTEXT_TOKENS 时截断。"""
    service = TopicSummaryService(providers=[])

    # 创建大量推文数据以触发截断
    tweets = []
    # 每条推文约 100 tokens（用长文本）
    long_text = "这是一条很长的推文。" * 50  # 约 ~250 中文字 ≈ 250 tokens
    for i in range(500):
        tweets.append({
            "tweet_id": str(i),
            "text": long_text,
            "author": "user_a",
            "created_at": f"2025-01-01 {i % 24:02d}:00",
            "translation": None,
        })

    prompt, count = service._build_prompt(tweets, ["user_a"], 24)

    # 应该截断，不是全部包含
    assert count < 500
    assert count > 0


# ── _call_llm_with_failover 测试 ──


@pytest.mark.asyncio
async def test_call_llm_first_provider_succeeds():
    """第一个 provider 成功直接返回。"""
    provider1 = _make_mock_provider("openrouter", succeed=True)
    provider2 = _make_mock_provider("minimax", succeed=True)

    service = TopicSummaryService(providers=[provider1, provider2])
    result = await service._call_llm_with_failover("test prompt")

    assert result is not None
    assert result.content == "这是LLM生成的摘要报告。"
    provider1.complete.assert_called_once()
    provider2.complete.assert_not_called()


@pytest.mark.asyncio
async def test_call_llm_failover_to_second():
    """第一个失败，fallback 到第二个。"""
    provider1 = _make_mock_provider("openrouter", succeed=False)
    resp2 = _make_llm_response(provider="minimax", content="来自第二个 provider")
    provider2 = _make_mock_provider("minimax", succeed=True, response=resp2)

    service = TopicSummaryService(providers=[provider1, provider2])
    result = await service._call_llm_with_failover("test prompt")

    assert result is not None
    assert result.content == "来自第二个 provider"
    provider1.complete.assert_called_once()
    provider2.complete.assert_called_once()


@pytest.mark.asyncio
async def test_call_llm_all_fail():
    """所有 provider 都失败返回 None。"""
    provider1 = _make_mock_provider("openrouter", succeed=False)
    provider2 = _make_mock_provider("minimax", succeed=False)

    service = TopicSummaryService(providers=[provider1, provider2])
    result = await service._call_llm_with_failover("test prompt")

    assert result is None


@pytest.mark.asyncio
async def test_call_llm_no_providers():
    """没有 provider 返回 None。"""
    service = TopicSummaryService(providers=[])
    result = await service._call_llm_with_failover("test prompt")

    assert result is None


@pytest.mark.asyncio
async def test_call_llm_provider_raises_exception():
    """provider.complete 抛异常也能 failover。"""
    provider1 = AsyncMock()
    provider1.get_provider_name.return_value = "openrouter"
    provider1.complete.side_effect = Exception("Connection timeout")

    resp2 = _make_llm_response(provider="minimax", content="Fallback result")
    provider2 = _make_mock_provider("minimax", succeed=True, response=resp2)

    service = TopicSummaryService(providers=[provider1, provider2])
    result = await service._call_llm_with_failover("test prompt")

    assert result is not None
    assert result.content == "Fallback result"


# ── create_and_execute_task 测试 ──


@pytest.mark.asyncio
async def test_create_task_topic_not_found(async_session, test_session_factory):
    """主题不存在时报错。"""
    service = TopicSummaryService(providers=[])

    with pytest.raises(ValueError, match="主题 ID 9999 不存在"):
        await service.create_and_execute_task(
            session=async_session,
            session_factory=test_session_factory,
            topic_id=9999,
            time_span_hours=24,
            deadline=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_create_task_no_accounts(async_session, test_session_factory, topic_repo):
    """主题无关联账号时报错。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.commit()

    service = TopicSummaryService(providers=[])

    with pytest.raises(ValueError, match="没有关联任何账号"):
        await service.create_and_execute_task(
            session=async_session,
            session_factory=test_session_factory,
            topic_id=topic.id,
            time_span_hours=24,
            deadline=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_create_task_returns_pending(async_session, test_session_factory, topic_repo):
    """成功创建任务返回 pending 状态。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()
    await topic_repo.add_account(async_session, _make_account(topic.id, "user_a"))
    await async_session.commit()

    service = TopicSummaryService(providers=[])

    deadline = datetime.now(timezone.utc)
    with patch("src.topic.services.topic_summary_service.asyncio.create_task"):
        task_domain = await service.create_and_execute_task(
            session=async_session,
            session_factory=test_session_factory,
            topic_id=topic.id,
            time_span_hours=24,
            deadline=deadline,
        )

    assert task_domain.status == TopicSummaryTaskStatus.pending
    assert task_domain.topic_id == topic.id
    assert task_domain.time_span_hours == 24


# ── _execute_task 完整流程测试（直接调用）──


@pytest.mark.asyncio
async def test_execute_task_no_tweets(async_session, test_session_factory, topic_repo, task_repo):
    """无推文时任务完成但摘要为提示信息。"""
    # 准备数据
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()
    await topic_repo.add_account(async_session, _make_account(topic.id, "user_a"))
    await async_session.flush()

    task_orm = TopicSummaryTaskOrm(
        topic_id=topic.id,
        time_span_hours=24,
        deadline=datetime.now(timezone.utc),
        status=TopicSummaryTaskStatus.pending.value,
    )
    await task_repo.create_task(async_session, task_orm)
    await async_session.commit()

    task_id = task_orm.id

    service = TopicSummaryService(providers=[])
    await service._execute_task(task_id, test_session_factory)

    # 验证任务状态
    async with test_session_factory() as check_session:
        task = await task_repo.get_task(check_session, task_id)
        assert task is not None
        assert task.status == TopicSummaryTaskStatus.completed.value
        assert task.completed_at is not None

        # 验证摘要内容
        summary = await task_repo.get_summary_by_task(check_session, task_id)
        assert summary is not None
        assert "没有找到推文数据" in summary.content
        assert summary.tweet_count == 0


@pytest.mark.asyncio
async def test_execute_task_with_tweets_and_llm(async_session, test_session_factory, topic_repo, task_repo):
    """有推文且 LLM 成功时，任务正确完成。"""
    from src.scraper.infrastructure.models import TweetOrm as TweetModel

    # 创建主题和账号
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()
    await topic_repo.add_account(async_session, _make_account(topic.id, "test_author"))
    await async_session.flush()

    # 创建推文数据
    now = datetime.now(timezone.utc)
    tweet = TweetModel(
        tweet_id="tweet_001",
        text="This is a test tweet about AI developments.",
        created_at=now - timedelta(hours=2),
        author_username="test_author",
    )
    async_session.add(tweet)
    await async_session.flush()

    # 创建任务
    task_orm = TopicSummaryTaskOrm(
        topic_id=topic.id,
        time_span_hours=24,
        deadline=now,
        status=TopicSummaryTaskStatus.pending.value,
    )
    await task_repo.create_task(async_session, task_orm)
    await async_session.commit()

    task_id = task_orm.id

    # Mock LLM provider
    mock_response = _make_llm_response(content="AI 发展摘要报告")
    mock_provider = _make_mock_provider("openrouter", succeed=True, response=mock_response)

    service = TopicSummaryService(providers=[mock_provider])
    await service._execute_task(task_id, test_session_factory)

    # 验证
    async with test_session_factory() as check_session:
        task = await task_repo.get_task(check_session, task_id)
        assert task.status == TopicSummaryTaskStatus.completed.value

        summary = await task_repo.get_summary_by_task(check_session, task_id)
        assert summary is not None
        assert summary.content == "AI 发展摘要报告"
        assert summary.tweet_count == 1
        assert summary.account_count == 1


@pytest.mark.asyncio
async def test_execute_task_llm_all_fail(async_session, test_session_factory, topic_repo, task_repo):
    """所有 LLM provider 失败时任务标记为 failed。"""
    from src.scraper.infrastructure.models import TweetOrm as TweetModel

    # 创建主题、账号和推文
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()
    await topic_repo.add_account(async_session, _make_account(topic.id, "fail_user"))
    await async_session.flush()

    now = datetime.now(timezone.utc)
    tweet = TweetModel(
        tweet_id="tweet_fail_001",
        text="Test tweet",
        created_at=now - timedelta(hours=1),
        author_username="fail_user",
    )
    async_session.add(tweet)
    await async_session.flush()

    task_orm = TopicSummaryTaskOrm(
        topic_id=topic.id,
        time_span_hours=24,
        deadline=now,
        status=TopicSummaryTaskStatus.pending.value,
    )
    await task_repo.create_task(async_session, task_orm)
    await async_session.commit()

    task_id = task_orm.id

    # 所有 provider 都失败
    fail_provider = _make_mock_provider("openrouter", succeed=False)
    service = TopicSummaryService(providers=[fail_provider])
    await service._execute_task(task_id, test_session_factory)

    # 验证任务失败
    async with test_session_factory() as check_session:
        task = await task_repo.get_task(check_session, task_id)
        assert task.status == TopicSummaryTaskStatus.failed.value
        assert "所有 LLM 提供商均不可用" in task.error_message


# ── 查询接口测试 ──


@pytest.mark.asyncio
async def test_get_task(async_session, topic_repo, task_repo):
    """get_task 返回域模型。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task_orm = TopicSummaryTaskOrm(
        topic_id=topic.id,
        time_span_hours=12,
        deadline=datetime.now(timezone.utc),
        status=TopicSummaryTaskStatus.pending.value,
    )
    await task_repo.create_task(async_session, task_orm)
    await async_session.commit()

    service = TopicSummaryService(providers=[])
    result = await service.get_task(async_session, task_orm.id)

    assert result is not None
    assert result.time_span_hours == 12
    assert result.status == TopicSummaryTaskStatus.pending


@pytest.mark.asyncio
async def test_get_task_not_found(async_session):
    """不存在的任务返回 None。"""
    service = TopicSummaryService(providers=[])
    result = await service.get_task(async_session, 9999)
    assert result is None


@pytest.mark.asyncio
async def test_list_tasks(async_session, topic_repo, task_repo):
    """list_tasks 返回域模型列表。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    for _ in range(3):
        task_orm = TopicSummaryTaskOrm(
            topic_id=topic.id,
            time_span_hours=24,
            deadline=datetime.now(timezone.utc),
            status=TopicSummaryTaskStatus.pending.value,
        )
        await task_repo.create_task(async_session, task_orm)
    await async_session.commit()

    service = TopicSummaryService(providers=[])
    tasks = await service.list_tasks(async_session, topic_id=topic.id)

    assert len(tasks) == 3
    for t in tasks:
        assert t.topic_id == topic.id


@pytest.mark.asyncio
async def test_delete_task(async_session, topic_repo, task_repo):
    """delete_task 成功删除。"""
    topic = _make_topic()
    await topic_repo.create(async_session, topic)
    await async_session.flush()

    task_orm = TopicSummaryTaskOrm(
        topic_id=topic.id,
        time_span_hours=24,
        deadline=datetime.now(timezone.utc),
        status=TopicSummaryTaskStatus.pending.value,
    )
    await task_repo.create_task(async_session, task_orm)
    await async_session.commit()

    service = TopicSummaryService(providers=[])
    deleted = await service.delete_task(async_session, task_orm.id)
    assert deleted is True

    found = await service.get_task(async_session, task_orm.id)
    assert found is None


# ── 单例模式测试 ──


def test_singleton_pattern():
    """get_instance 返回同一实例，reset 后返回新实例。"""
    TopicSummaryService.reset_instance()

    instance1 = TopicSummaryService.get_instance()
    instance2 = TopicSummaryService.get_instance()
    assert instance1 is instance2

    TopicSummaryService.reset_instance()
    instance3 = TopicSummaryService.get_instance()
    assert instance3 is not instance1

    # 清理
    TopicSummaryService.reset_instance()
