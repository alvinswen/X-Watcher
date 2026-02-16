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
    ChunkTracker,
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
    """测试失败后重入队列，保留分块信息。"""
    queue = _create_queue(mock_registry)
    # 使用非常短的 retry delay 以加速测试
    queue.RETRY_BASE_DELAY = 0.1

    # 初始化 tracker（模拟多分块任务）
    queue._task_chunk_trackers["test-task"] = ChunkTracker(
        total_chunks=3, total_tweets_requested=120
    )

    request = SummarizationRequest(
        priority=SummarizationPriority.NORMAL.value,
        tweet_ids=["tweet1"],
        source="scraping",
        task_id="test-task",
        retry_count=0,
        chunk_index=1,
        total_chunks=3,
    )

    await queue._handle_failure(request, Exception("test error"))

    # 应该有一个重试请求入队
    assert queue.queue_size == 1

    retry_req = await queue._queue.get()
    assert retry_req.retry_count == 1
    assert retry_req.priority == SummarizationPriority.LOW.value
    assert retry_req.source == "retry"
    assert retry_req.tweet_ids == ["tweet1"]
    # 分块信息应被保留
    assert retry_req.chunk_index == 1
    assert retry_req.total_chunks == 3


@pytest.mark.asyncio
async def test_max_retry_exceeded(mock_settings, mock_registry):
    """测试超过最大重试次数后放弃，标记分块失败。"""
    queue = _create_queue(mock_registry)
    queue.RETRY_BASE_DELAY = 0.01

    # 单分块任务：失败后整个任务应标记为 FAILED
    queue._task_chunk_trackers["test-task"] = ChunkTracker(
        total_chunks=1, total_tweets_requested=1
    )

    request = SummarizationRequest(
        priority=SummarizationPriority.LOW.value,
        tweet_ids=["tweet1"],
        source="retry",
        task_id="test-task",
        retry_count=SummarizationQueue.MAX_RETRY_COUNT,  # 已达最大重试
        chunk_index=0,
        total_chunks=1,
    )

    await queue._handle_failure(request, Exception("final error"))

    # 不应该有重试请求入队
    assert queue.queue_size == 0

    # 任务应标记为 FAILED（因为唯一的分块失败了）
    from src.scraper.task_registry import TaskStatus

    mock_registry.update_task_status.assert_called_once()
    call_args = mock_registry.update_task_status.call_args
    assert call_args[0][0] == "test-task"
    assert call_args[0][1] == TaskStatus.FAILED

    # tracker 应被清理
    assert "test-task" not in queue._task_chunk_trackers


# ========== 跨线程入队测试 ==========


@pytest.mark.asyncio
async def test_enqueue_threadsafe(mock_settings, mock_registry):
    """测试从其他线程安全入队。"""
    queue = _create_queue(mock_registry)
    # 停止 worker 处理以便检查队列
    queue._running = False

    # 手动设置 _loop
    loop = asyncio.get_running_loop()
    queue._loop = loop

    result: list[str | None] = [None]
    thread_done = asyncio.Event()

    def thread_func():
        result[0] = queue.enqueue_threadsafe(
            ["tweet_from_thread"],
            source="scraping",
            priority=SummarizationPriority.NORMAL,
        )
        # 从线程安全地设置事件
        loop.call_soon_threadsafe(thread_done.set)

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


# ========== 分块跟踪测试 ==========


@pytest.mark.asyncio
async def test_enqueue_initializes_chunk_tracker(mock_settings, mock_registry):
    """测试入队时初始化 ChunkTracker。"""
    queue = _create_queue(mock_registry, batch_size=50)

    tweet_ids = [f"tweet_{i}" for i in range(120)]
    task_id = await queue.enqueue(tweet_ids, source="batch_api")

    # ChunkTracker 应被创建
    assert task_id in queue._task_chunk_trackers
    tracker = queue._task_chunk_trackers[task_id]
    assert tracker.total_chunks == 3
    assert tracker.total_tweets_requested == 120
    assert tracker.completed_chunks == 0
    assert tracker.failed_chunks == 0

    # 进度应被初始化
    mock_registry.update_progress.assert_called_once_with(task_id, 0, 3)


@pytest.mark.asyncio
async def test_chunk_requests_carry_index_and_total(mock_settings, mock_registry):
    """测试分块请求包含 chunk_index 和 total_chunks。"""
    queue = _create_queue(mock_registry, batch_size=50)

    tweet_ids = [f"tweet_{i}" for i in range(120)]
    await queue.enqueue(tweet_ids, source="batch_api")

    # 出队所有 3 个分块请求并检查元数据
    req0 = await queue._queue.get()
    req1 = await queue._queue.get()
    req2 = await queue._queue.get()

    assert req0.chunk_index == 0 and req0.total_chunks == 3
    assert req1.chunk_index == 1 and req1.total_chunks == 3
    assert req2.chunk_index == 2 and req2.total_chunks == 3
    assert len(req0.tweet_ids) == 50
    assert len(req1.tweet_ids) == 50
    assert len(req2.tweet_ids) == 20


@pytest.mark.asyncio
async def test_task_not_completed_until_all_chunks_done(mock_settings, mock_registry):
    """测试只有所有分块完成后任务才标记为 COMPLETED。"""
    from src.scraper.task_registry import TaskStatus
    from src.summarization.domain.models import SummaryResult

    queue = _create_queue(mock_registry, batch_size=50)
    task_id = "test-multi-chunk-task"

    queue._task_chunk_trackers[task_id] = ChunkTracker(
        total_chunks=3, total_tweets_requested=120
    )

    mock_result = SummaryResult(
        total_tweets=50, total_tweets_succeeded=50,
        total_groups=10, independent_tweets=0,
        cache_hits=5, cache_misses=45, total_tokens=1000,
        total_cost_usd=0.01, providers_used={"openrouter": 45},
        processing_time_ms=500,
    )

    # 第一个分块完成 — 任务不应标记为完成
    req1 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=0, total_chunks=3,
    )
    queue._record_chunk_success(req1, mock_result)
    mock_registry.update_task_status.assert_not_called()

    # 进度应更新
    mock_registry.update_progress.assert_called_with(task_id, 1, 3)

    # 第二个分块完成 — 仍不应完成
    req2 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=1, total_chunks=3,
    )
    queue._record_chunk_success(req2, mock_result)
    mock_registry.update_task_status.assert_not_called()

    # 第三个分块完成 — 现在任务应标记为 COMPLETED
    req3 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 20,
        task_id=task_id, chunk_index=2, total_chunks=3,
    )
    queue._record_chunk_success(req3, mock_result)

    mock_registry.update_task_status.assert_called_once()
    call_args = mock_registry.update_task_status.call_args
    assert call_args[0][0] == task_id
    assert call_args[0][1] == TaskStatus.COMPLETED

    result = call_args[1]["result"]
    assert result["total_tweets_summarized"] == 150  # 3 * 50
    assert result["chunks"]["total"] == 3
    assert result["chunks"]["completed"] == 3
    assert result["chunks"]["failed"] == 0
    assert result["total_cost_usd"] == pytest.approx(0.03)  # 3 * 0.01

    # tracker 应被清理
    assert task_id not in queue._task_chunk_trackers


@pytest.mark.asyncio
async def test_partial_chunk_failure_still_completes(mock_settings, mock_registry):
    """测试部分分块失败时任务仍标记为 COMPLETED（部分成功）。"""
    from src.scraper.task_registry import TaskStatus
    from src.summarization.domain.models import SummaryResult

    queue = _create_queue(mock_registry, batch_size=50)
    task_id = "test-partial-failure"

    queue._task_chunk_trackers[task_id] = ChunkTracker(
        total_chunks=3, total_tweets_requested=120
    )

    mock_result = SummaryResult(
        total_tweets=50, total_tweets_succeeded=50,
        total_groups=10, independent_tweets=0,
        cache_hits=5, cache_misses=45, total_tokens=1000,
        total_cost_usd=0.01, providers_used={"openrouter": 45},
        processing_time_ms=500,
    )

    # 第一个分块成功
    req1 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=0, total_chunks=3,
    )
    queue._record_chunk_success(req1, mock_result)

    # 第二个分块失败
    req2 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=1, total_chunks=3,
    )
    queue._record_chunk_failure(req2, Exception("LLM error"))

    # 第三个分块成功
    req3 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 20,
        task_id=task_id, chunk_index=2, total_chunks=3,
    )
    queue._record_chunk_success(req3, mock_result)

    # 任务应标记为 COMPLETED（部分成功）
    mock_registry.update_task_status.assert_called_once()
    call_args = mock_registry.update_task_status.call_args
    assert call_args[0][1] == TaskStatus.COMPLETED
    result = call_args[1]["result"]
    assert result["chunks"]["completed"] == 2
    assert result["chunks"]["failed"] == 1
    assert result["total_tweets_summarized"] == 100  # 2 * 50
    assert len(result["failed_tweet_ids"]) == 50  # 失败分块的推文数


@pytest.mark.asyncio
async def test_all_chunks_fail_marks_task_failed(mock_settings, mock_registry):
    """测试所有分块失败时任务标记为 FAILED。"""
    from src.scraper.task_registry import TaskStatus

    queue = _create_queue(mock_registry, batch_size=50)
    task_id = "test-all-fail"

    queue._task_chunk_trackers[task_id] = ChunkTracker(
        total_chunks=2, total_tweets_requested=80
    )

    req1 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=0, total_chunks=2,
    )
    queue._record_chunk_failure(req1, Exception("error 1"))

    req2 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 30,
        task_id=task_id, chunk_index=1, total_chunks=2,
    )
    queue._record_chunk_failure(req2, Exception("error 2"))

    mock_registry.update_task_status.assert_called_once()
    call_args = mock_registry.update_task_status.call_args
    assert call_args[0][1] == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_enqueue_metadata_includes_task_type(mock_settings, mock_registry):
    """测试入队时 metadata 包含任务类型。"""
    queue = _create_queue(mock_registry, batch_size=50)

    # backfill 类型
    await queue.enqueue(
        ["t1"], source="batch_api", priority=SummarizationPriority.HIGH
    )
    call_kwargs = mock_registry.create_task.call_args[1]
    assert call_kwargs["metadata"]["task_type"] == "backfill"


def test_classify_task_type():
    """测试任务类型推断。"""
    assert SummarizationQueue._classify_task_type("batch_api", False) == "backfill"
    assert SummarizationQueue._classify_task_type("batch_api", True) == "reset"
    assert SummarizationQueue._classify_task_type("scraping", False) == "scraping"
    assert SummarizationQueue._classify_task_type("deduplication", False) == "deduplication"
    assert SummarizationQueue._classify_task_type("retry", False) == "retry"
    assert SummarizationQueue._classify_task_type("unknown_source", False) == "unknown"


@pytest.mark.asyncio
async def test_chunk_success_propagates_individual_failures(mock_settings, mock_registry):
    """测试 _record_chunk_success 传播单条推文级别的失败信息。"""
    from src.summarization.domain.models import SummaryResult

    queue = _create_queue(mock_registry, batch_size=50)
    task_id = "test-individual-failures"

    queue._task_chunk_trackers[task_id] = ChunkTracker(
        total_chunks=1, total_tweets_requested=50
    )

    # 模拟分块成功但包含个别推文失败
    mock_result = SummaryResult(
        total_tweets=50, total_tweets_succeeded=47,
        total_groups=0, independent_tweets=50,
        cache_hits=0, cache_misses=47, total_tokens=1000,
        total_cost_usd=0.01, providers_used={"openrouter": 47},
        processing_time_ms=500,
        failed_tweets=[
            {"tweet_id": "t1", "error_type": "llm_failure", "error_message": "timeout", "group_id": None},
            {"tweet_id": "t2", "error_type": "llm_failure", "error_message": "rate limit", "group_id": None},
            {"tweet_id": "t3", "error_type": "llm_failure", "error_message": "parse error", "group_id": None},
        ],
    )

    req = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=0, total_chunks=1,
    )
    queue._record_chunk_success(req, mock_result)

    tracker = queue._task_chunk_trackers.get(task_id)
    # tracker 已被清理（单分块任务完成后删除），检查最终结果
    call_args = mock_registry.update_task_status.call_args
    result = call_args[1]["result"]
    assert result["total_tweets_summarized"] == 47
    assert len(result["failed_tweet_ids"]) == 3
    assert result["failed_tweet_ids"][0]["tweet_id"] == "t1"


@pytest.mark.asyncio
async def test_total_tweets_summarized_uses_succeeded_count(mock_settings, mock_registry):
    """测试 total_tweets_summarized 使用 total_tweets_succeeded 而非 total_tweets。"""
    from src.scraper.task_registry import TaskStatus
    from src.summarization.domain.models import SummaryResult

    queue = _create_queue(mock_registry, batch_size=100)
    task_id = "test-succeeded-count"

    queue._task_chunk_trackers[task_id] = ChunkTracker(
        total_chunks=2, total_tweets_requested=100
    )

    # 第一个分块：50 输入，45 成功
    result1 = SummaryResult(
        total_tweets=50, total_tweets_succeeded=45,
        total_groups=0, independent_tweets=50,
        cache_hits=0, cache_misses=45, total_tokens=500,
        total_cost_usd=0.005, providers_used={"openrouter": 45},
        processing_time_ms=300,
        failed_tweets=[
            {"tweet_id": f"f{i}", "error_type": "llm_failure",
             "error_message": "error", "group_id": None}
            for i in range(5)
        ],
    )
    req1 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=0, total_chunks=2,
    )
    queue._record_chunk_success(req1, result1)

    # 第二个分块：50 输入，48 成功
    result2 = SummaryResult(
        total_tweets=50, total_tweets_succeeded=48,
        total_groups=0, independent_tweets=50,
        cache_hits=0, cache_misses=48, total_tokens=600,
        total_cost_usd=0.006, providers_used={"openrouter": 48},
        processing_time_ms=400,
        failed_tweets=[
            {"tweet_id": f"g{i}", "error_type": "llm_failure",
             "error_message": "error", "group_id": None}
            for i in range(2)
        ],
    )
    req2 = SummarizationRequest(
        priority=0, tweet_ids=["t"] * 50,
        task_id=task_id, chunk_index=1, total_chunks=2,
    )
    queue._record_chunk_success(req2, result2)

    # 验证聚合结果
    mock_registry.update_task_status.assert_called_once()
    call_args = mock_registry.update_task_status.call_args
    assert call_args[0][1] == TaskStatus.COMPLETED
    result = call_args[1]["result"]
    assert result["total_tweets_summarized"] == 93  # 45 + 48, 不是 50 + 50
    assert len(result["failed_tweet_ids"]) == 7  # 5 + 2
