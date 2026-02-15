"""摘要任务队列单元测试。

测试 SummarizationQueue 的核心逻辑，包括：
- 入队/出队处理
- 优先级排序
- 批次分块
- 背压（队列满）
- 重试机制
- 启动/停止生命周期
- 跨线程入队
- TaskRegistry 集成
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.summarization.services.summarization_queue import (
    SummarizationPriority,
    SummarizationQueue,
    SummarizationRequest,
)


@pytest.fixture(autouse=True)
def reset_queue():
    """每个测试前后重置队列单例。"""
    SummarizationQueue.reset_instance()
    yield
    SummarizationQueue.reset_instance()


@pytest.fixture
def mock_registry():
    """Mock TaskRegistry。"""
    registry = MagicMock()
    registry.create_task.return_value = "test-task-id"
    registry.update_task_status = MagicMock()
    return registry


@pytest.fixture
def mock_settings(monkeypatch):
    """Mock 配置。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("TWITTER_API_KEY", "test-key")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("AUTO_SUMMARIZATION_BATCH_SIZE", "50")
    from src.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()


def _create_queue(mock_registry, batch_size=50):
    """创建队列实例并注入 mock。"""
    queue = SummarizationQueue.get_instance()
    queue._registry = mock_registry
    queue._batch_size = batch_size
    return queue


# ========== 基础功能测试 ==========


@pytest.mark.asyncio
async def test_singleton(mock_settings):
    """测试单例模式。"""
    q1 = SummarizationQueue.get_instance()
    q2 = SummarizationQueue.get_instance()
    assert q1 is q2


@pytest.mark.asyncio
async def test_reset_instance(mock_settings):
    """测试重置单例。"""
    q1 = SummarizationQueue.get_instance()
    SummarizationQueue.reset_instance()
    q2 = SummarizationQueue.get_instance()
    assert q1 is not q2


# ========== 入队测试 ==========


@pytest.mark.asyncio
async def test_enqueue_basic(mock_settings, mock_registry):
    """测试基本入队。"""
    queue = _create_queue(mock_registry)
    await queue.start()

    try:
        # 停止 worker 以便检查队列内容
        queue._running = False
        await asyncio.sleep(0.1)

        task_id = await queue.enqueue(
            ["tweet1", "tweet2"],
            source="scraping",
            priority=SummarizationPriority.NORMAL,
        )

        assert task_id == "test-task-id"
        assert queue.queue_size >= 1
        mock_registry.create_task.assert_called_once()
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_enqueue_with_existing_task_id(mock_settings, mock_registry):
    """测试使用已有 task_id 入队不会创建新任务。"""
    queue = _create_queue(mock_registry)

    task_id = await queue.enqueue(
        ["tweet1"],
        source="batch_api",
        task_id="existing-task-id",
    )

    assert task_id == "existing-task-id"
    mock_registry.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_empty_tweet_ids(mock_settings, mock_registry):
    """测试空推文 ID 列表入队。"""
    queue = _create_queue(mock_registry)

    task_id = await queue.enqueue([], source="scraping")
    # 空列表不会产生任何分块
    assert queue.queue_size == 0


# ========== 分块测试 ==========


@pytest.mark.asyncio
async def test_batch_chunking(mock_settings, mock_registry):
    """测试大批量按 batch_size 分块。"""
    queue = _create_queue(mock_registry, batch_size=50)

    # 120 条推文应分成 3 块 (50, 50, 20)
    tweet_ids = [f"tweet_{i}" for i in range(120)]
    await queue.enqueue(tweet_ids, source="batch_api")

    assert queue.queue_size == 3


@pytest.mark.asyncio
async def test_batch_chunking_exact_multiple(mock_settings, mock_registry):
    """测试恰好是 batch_size 倍数时的分块。"""
    queue = _create_queue(mock_registry, batch_size=50)

    tweet_ids = [f"tweet_{i}" for i in range(100)]
    await queue.enqueue(tweet_ids, source="batch_api")

    assert queue.queue_size == 2


@pytest.mark.asyncio
async def test_batch_chunking_smaller_than_batch(mock_settings, mock_registry):
    """测试小于 batch_size 时不分块。"""
    queue = _create_queue(mock_registry, batch_size=50)

    tweet_ids = [f"tweet_{i}" for i in range(10)]
    await queue.enqueue(tweet_ids, source="scraping")

    assert queue.queue_size == 1


# ========== 优先级排序测试 ==========


@pytest.mark.asyncio
async def test_priority_ordering(mock_settings, mock_registry):
    """测试优先级排序：HIGH > NORMAL > LOW。"""
    queue = _create_queue(mock_registry)

    # 按 NORMAL → LOW → HIGH 顺序入队
    await queue.enqueue(
        ["normal_1"], source="scraping", priority=SummarizationPriority.NORMAL
    )
    await queue.enqueue(
        ["low_1"], source="retry", priority=SummarizationPriority.LOW
    )
    await queue.enqueue(
        ["high_1"], source="batch_api", priority=SummarizationPriority.HIGH
    )

    # 出队顺序应为 HIGH → NORMAL → LOW
    req1 = await queue._queue.get()
    req2 = await queue._queue.get()
    req3 = await queue._queue.get()

    assert req1.priority == SummarizationPriority.HIGH.value
    assert req1.tweet_ids == ["high_1"]
    assert req2.priority == SummarizationPriority.NORMAL.value
    assert req2.tweet_ids == ["normal_1"]
    assert req3.priority == SummarizationPriority.LOW.value
    assert req3.tweet_ids == ["low_1"]


# ========== 背压测试 ==========


@pytest.mark.asyncio
async def test_backpressure_queue_full(mock_settings, mock_registry):
    """测试队列满时不阻塞，记录警告。"""
    queue = _create_queue(mock_registry, batch_size=1)

    # 创建一个很小的队列
    queue._queue = asyncio.PriorityQueue(maxsize=3)

    # 入队 5 条推文（每条 1 个分块），只有 3 个能入队
    tweet_ids = [f"tweet_{i}" for i in range(5)]
    task_id = await queue.enqueue(
        tweet_ids, source="scraping", priority=SummarizationPriority.NORMAL
    )

    # 应该有 3 个入队成功
    assert queue.queue_size == 3
    # task_id 应该仍然返回
    assert task_id is not None


# ========== 生命周期测试 ==========


@pytest.mark.asyncio
async def test_start_stop_lifecycle(mock_settings, mock_registry):
    """测试启动/停止生命周期。"""
    queue = _create_queue(mock_registry)

    assert not queue.is_running

    await queue.start()
    assert queue.is_running
    assert queue._worker is not None
    assert queue._loop is not None

    await queue.stop()
    assert not queue.is_running
    assert queue._worker is None


@pytest.mark.asyncio
async def test_start_idempotent(mock_settings, mock_registry):
    """测试重复启动是幂等的。"""
    queue = _create_queue(mock_registry)

    await queue.start()
    worker_1 = queue._worker

    await queue.start()  # 重复启动
    worker_2 = queue._worker

    assert worker_1 is worker_2  # 同一个 worker
    await queue.stop()


@pytest.mark.asyncio
async def test_stop_idempotent(mock_settings, mock_registry):
    """测试重复停止是幂等的。"""
    queue = _create_queue(mock_registry)

    await queue.start()
    await queue.stop()
    await queue.stop()  # 重复停止不抛异常

    assert not queue.is_running


# ========== Worker 处理测试 ==========


@pytest.mark.asyncio
async def test_worker_processes_request(mock_settings, mock_registry):
    """测试 worker 正常处理请求。"""
    queue = _create_queue(mock_registry)

    # Mock _process_request
    processed = []
    original_process = queue._process_request

    async def mock_process(request):
        processed.append(request)

    queue._process_request = mock_process

    await queue.start()

    # 入队
    await queue.enqueue(
        ["tweet1", "tweet2"], source="scraping"
    )

    # 等待处理
    await asyncio.sleep(0.5)

    assert len(processed) == 1
    assert processed[0].tweet_ids == ["tweet1", "tweet2"]
    assert processed[0].source == "scraping"

    await queue.stop()


@pytest.mark.asyncio
async def test_worker_processes_multiple_requests(mock_settings, mock_registry):
    """测试 worker 串行处理多个请求。"""
    queue = _create_queue(mock_registry, batch_size=2)

    processed = []

    async def mock_process(request):
        processed.append(request.tweet_ids)

    queue._process_request = mock_process

    await queue.start()

    # 入队多个请求
    await queue.enqueue(["t1", "t2"], source="scraping")
    await queue.enqueue(["t3", "t4"], source="deduplication")

    # 等待处理
    await asyncio.sleep(1.0)

    assert len(processed) == 2

    await queue.stop()


# ========== 重试测试 ==========


@pytest.mark.asyncio
async def test_retry_on_failure(mock_settings, mock_registry):
    """测试失败后重入队列。"""
    queue = _create_queue(mock_registry)
    # 使用非常短的 retry delay 以加速测试
    queue.RETRY_BASE_DELAY = 0.1

    request = SummarizationRequest(
        priority=SummarizationPriority.NORMAL.value,
        tweet_ids=["tweet1"],
        source="scraping",
        task_id="test-task",
        retry_count=0,
    )

    await queue._handle_failure(request, Exception("test error"))

    # 应该有一个重试请求入队
    assert queue.queue_size == 1

    retry_req = await queue._queue.get()
    assert retry_req.retry_count == 1
    assert retry_req.priority == SummarizationPriority.LOW.value
    assert retry_req.source == "retry"
    assert retry_req.tweet_ids == ["tweet1"]


@pytest.mark.asyncio
async def test_max_retry_exceeded(mock_settings, mock_registry):
    """测试超过最大重试次数后放弃。"""
    queue = _create_queue(mock_registry)
    queue.RETRY_BASE_DELAY = 0.01

    request = SummarizationRequest(
        priority=SummarizationPriority.LOW.value,
        tweet_ids=["tweet1"],
        source="retry",
        task_id="test-task",
        retry_count=SummarizationQueue.MAX_RETRY_COUNT,  # 已达最大重试
    )

    await queue._handle_failure(request, Exception("final error"))

    # 不应该有重试请求入队
    assert queue.queue_size == 0

    # 任务应标记为 FAILED
    from src.scraper.task_registry import TaskStatus

    mock_registry.update_task_status.assert_called_once()
    call_args = mock_registry.update_task_status.call_args
    assert call_args[0][0] == "test-task"
    assert call_args[0][1] == TaskStatus.FAILED


# ========== 跨线程入队测试 ==========


@pytest.mark.asyncio
async def test_enqueue_threadsafe(mock_settings, mock_registry):
    """测试从其他线程安全入队。"""
    queue = _create_queue(mock_registry)
    # 停止 worker 处理以便检查队列
    queue._running = False

    # 手动设置 _loop
    queue._loop = asyncio.get_running_loop()

    result = [None]
    thread_done = asyncio.Event()

    def thread_func():
        result[0] = queue.enqueue_threadsafe(
            ["tweet_from_thread"],
            source="scraping",
            priority=SummarizationPriority.NORMAL,
        )
        # 从线程安全地设置事件
        queue._loop.call_soon_threadsafe(thread_done.set)

    thread = threading.Thread(target=thread_func)
    thread.start()

    # 使用 asyncio 等待而不是 thread.join()，让事件循环继续处理
    await asyncio.wait_for(thread_done.wait(), timeout=15)
    thread.join(timeout=1)

    assert result[0] == "test-task-id"
    assert queue.queue_size == 1


@pytest.mark.asyncio
async def test_enqueue_threadsafe_when_not_started(mock_settings, mock_registry):
    """测试队列未启动时跨线程入队返回 None。"""
    queue = _create_queue(mock_registry)
    # _loop 为 None（未启动）

    result = queue.enqueue_threadsafe(
        ["tweet1"], source="scraping"
    )

    assert result is None


# ========== TaskRegistry 集成测试 ==========


@pytest.mark.asyncio
async def test_task_registry_creates_task_on_enqueue(mock_settings, mock_registry):
    """测试入队时创建 TaskRegistry 任务。"""
    queue = _create_queue(mock_registry)

    await queue.enqueue(
        ["tweet1", "tweet2"],
        source="batch_api",
        priority=SummarizationPriority.HIGH,
    )

    mock_registry.create_task.assert_called_once()
    call_kwargs = mock_registry.create_task.call_args[1]
    assert "batch_api" in call_kwargs["metadata"]["source"]
    assert call_kwargs["metadata"]["tweet_count"] == 2


# ========== SummarizationRequest 排序测试 ==========


def test_request_ordering():
    """测试 SummarizationRequest 按 priority 排序。"""
    high = SummarizationRequest(
        priority=SummarizationPriority.HIGH.value,
        tweet_ids=["h1"],
        source="batch_api",
    )
    normal = SummarizationRequest(
        priority=SummarizationPriority.NORMAL.value,
        tweet_ids=["n1"],
        source="scraping",
    )
    low = SummarizationRequest(
        priority=SummarizationPriority.LOW.value,
        tweet_ids=["l1"],
        source="retry",
    )

    # 排序后顺序: HIGH < NORMAL < LOW
    sorted_reqs = sorted([normal, low, high])
    assert sorted_reqs[0].priority == SummarizationPriority.HIGH.value
    assert sorted_reqs[1].priority == SummarizationPriority.NORMAL.value
    assert sorted_reqs[2].priority == SummarizationPriority.LOW.value


# ========== Queue 属性测试 ==========


@pytest.mark.asyncio
async def test_queue_size_property(mock_settings, mock_registry):
    """测试 queue_size 属性。"""
    queue = _create_queue(mock_registry)

    assert queue.queue_size == 0

    await queue.enqueue(["t1"], source="test")
    assert queue.queue_size == 1

    await queue.enqueue(["t2"], source="test")
    assert queue.queue_size == 2


@pytest.mark.asyncio
async def test_is_running_property(mock_settings, mock_registry):
    """测试 is_running 属性。"""
    queue = _create_queue(mock_registry)

    assert not queue.is_running

    await queue.start()
    assert queue.is_running

    await queue.stop()
    assert not queue.is_running
