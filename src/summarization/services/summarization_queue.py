"""摘要任务队列。

集中管理摘要任务的调度、并发控制和重试。
替代散落在 ScrapingService 和 DeduplicationService 中的 fire-and-forget 模式。

设计要点：
- 使用 asyncio.PriorityQueue 实现有界优先级队列
- 单 worker 串行处理请求，内部 asyncio.gather + 全局 Semaphore(5) 仍可并发调用 LLM
- 支持跨线程安全入队（APScheduler 后台线程通过 run_coroutine_threadsafe）
- 内置指数退避重试机制
- 集成 TaskRegistry 实现可观测性
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum

from src.config import get_settings
from src.scraper.task_registry import TaskRegistry, TaskStatus

logger = logging.getLogger(__name__)


class SummarizationPriority(IntEnum):
    """摘要任务优先级。数值越小优先级越高。"""

    HIGH = 0  # 手动 batch API / regenerate
    NORMAL = 10  # 自动触发（抓取/去重后）
    LOW = 20  # 重试任务


@dataclass(order=True)
class SummarizationRequest:
    """摘要请求项。放入优先级队列时按 priority 排序。"""

    priority: int
    # 以下字段不参与排序比较
    tweet_ids: list[str] = field(compare=False)
    force_refresh: bool = field(default=False, compare=False)
    source: str = field(default="unknown", compare=False)
    task_id: str | None = field(default=None, compare=False)
    retry_count: int = field(default=0, compare=False)
    created_at: float = field(default_factory=time.time, compare=False)


class SummarizationQueue:
    """摘要任务队列（单例）。

    - 使用 asyncio.PriorityQueue 实现有界队列
    - 单 worker 串行处理请求
    - worker 从队列取任务，按 batch_size 分块处理
    - 集成 TaskRegistry 实现可观测性
    - 内置重试机制（带指数退避）
    - 支持跨线程安全入队
    """

    _instance: "SummarizationQueue | None" = None

    # 配置常量
    MAX_QUEUE_SIZE = 100
    MAX_RETRY_COUNT = 3
    RETRY_BASE_DELAY = 5.0  # 秒

    def __init__(self) -> None:
        """初始化队列。

        注意：不要直接调用此构造函数，使用 get_instance() 获取单例。
        """
        settings = get_settings()
        self._queue: asyncio.PriorityQueue[SummarizationRequest] = (
            asyncio.PriorityQueue(maxsize=self.MAX_QUEUE_SIZE)
        )
        self._worker: asyncio.Task | None = None
        self._batch_size: int = settings.auto_summarization_batch_size
        self._running: bool = False
        self._registry: TaskRegistry = TaskRegistry.get_instance()
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get_instance(cls) -> "SummarizationQueue":
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅用于测试）。"""
        if cls._instance is not None:
            cls._instance._running = False
        cls._instance = None

    async def start(self) -> None:
        """启动 worker 协程。在 app lifespan 启动时调用。"""
        if self._running:
            return

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._worker = asyncio.create_task(
            self._worker_loop(),
            name="summarization-worker",
        )
        logger.info("摘要队列已启动: 1 个 worker")

    async def stop(self) -> None:
        """优雅停止。在 app lifespan 关闭时调用。"""
        if not self._running:
            return

        self._running = False

        # 发送 sentinel 让 worker 退出等待
        try:
            self._queue.put_nowait(
                SummarizationRequest(
                    priority=999, tweet_ids=[], source="shutdown"
                )
            )
        except asyncio.QueueFull:
            pass

        # 等待 worker 完成当前任务
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

        self._loop = None
        logger.info("摘要队列已停止")

    async def enqueue(
        self,
        tweet_ids: list[str],
        *,
        force_refresh: bool = False,
        source: str = "unknown",
        priority: SummarizationPriority = SummarizationPriority.NORMAL,
        task_id: str | None = None,
    ) -> str:
        """将摘要请求加入队列。

        如果队列满，记录警告但不阻塞调用者（backpressure 信号）。

        Args:
            tweet_ids: 推文 ID 列表
            force_refresh: 是否强制刷新缓存
            source: 触发来源（scraping/deduplication/batch_api/retry）
            priority: 优先级
            task_id: 任务 ID（可选，未提供时自动创建）

        Returns:
            task_id: 任务 ID（用于查询进度）
        """
        # 创建 task_id（如果调用者没有提供）
        if task_id is None:
            task_id = self._registry.create_task(
                task_name=f"摘要 {len(tweet_ids)} 条推文",
                metadata={
                    "tweet_count": len(tweet_ids),
                    "tweet_ids": tweet_ids[:10],
                    "source": source,
                    "force_refresh": force_refresh,
                },
            )

        # 按 batch_size 分块
        chunks = [
            tweet_ids[i : i + self._batch_size]
            for i in range(0, len(tweet_ids), self._batch_size)
        ]

        enqueued_count = 0
        dropped_count = 0

        for chunk in chunks:
            request = SummarizationRequest(
                priority=priority.value,
                tweet_ids=chunk,
                force_refresh=force_refresh,
                source=source,
                task_id=task_id,
            )
            try:
                self._queue.put_nowait(request)
                enqueued_count += 1
            except asyncio.QueueFull:
                dropped_count += len(chunk)
                logger.warning(
                    f"摘要队列已满 (size={self.MAX_QUEUE_SIZE})，"
                    f"丢弃 {len(chunk)} 条推文的摘要请求 (source={source})"
                )
                # 更新 Prometheus 指标
                try:
                    from src.monitoring.metrics import (
                        summarization_queue_dropped_total,
                    )

                    summarization_queue_dropped_total.inc(len(chunk))
                except ImportError:
                    pass

        # 更新 Prometheus 指标
        try:
            from src.monitoring.metrics import (
                summarization_queue_enqueued_total,
                summarization_queue_size,
            )

            summarization_queue_enqueued_total.labels(source=source).inc(
                enqueued_count
            )
            summarization_queue_size.set(self._queue.qsize())
        except ImportError:
            pass

        logger.info(
            f"摘要请求已入队: {len(tweet_ids)} 条推文, "
            f"{len(chunks)} 个分块 (入队 {enqueued_count}, 丢弃 {dropped_count}), "
            f"source={source}, queue_size={self._queue.qsize()}"
        )

        return task_id

    def enqueue_threadsafe(
        self,
        tweet_ids: list[str],
        *,
        force_refresh: bool = False,
        source: str = "unknown",
        priority: SummarizationPriority = SummarizationPriority.NORMAL,
        task_id: str | None = None,
    ) -> str | None:
        """跨线程安全入队。

        用于 APScheduler 后台线程或其他非主事件循环的线程。
        通过 asyncio.run_coroutine_threadsafe 将入队操作调度到主事件循环。

        Args:
            tweet_ids: 推文 ID 列表
            force_refresh: 是否强制刷新缓存
            source: 触发来源
            priority: 优先级
            task_id: 任务 ID（可选）

        Returns:
            task_id 或 None（队列未启动时）
        """
        if self._loop is None or self._loop.is_closed():
            logger.warning("摘要队列未启动或事件循环已关闭，忽略入队请求")
            return None

        try:
            future = asyncio.run_coroutine_threadsafe(
                self.enqueue(
                    tweet_ids,
                    force_refresh=force_refresh,
                    source=source,
                    priority=priority,
                    task_id=task_id,
                ),
                self._loop,
            )
            # 等待入队完成（最多 10 秒）
            return future.result(timeout=10)
        except Exception as e:
            logger.warning(f"跨线程入队失败: {e}")
            return None

    @property
    def queue_size(self) -> int:
        """当前队列中的任务数。"""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """队列是否正在运行。"""
        return self._running

    async def _worker_loop(self) -> None:
        """Worker 主循环。"""
        logger.info("摘要 Worker 已启动")

        while self._running:
            try:
                # 使用超时避免 stop 时永久阻塞
                request = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # 检查 sentinel（shutdown 信号）
            if not request.tweet_ids:
                self._queue.task_done()
                break

            try:
                await self._process_request(request)
            except Exception as e:
                logger.exception(f"Worker 处理摘要请求异常: {e}")
                await self._handle_failure(request, e)
            finally:
                self._queue.task_done()
                # 更新队列大小指标
                try:
                    from src.monitoring.metrics import summarization_queue_size

                    summarization_queue_size.set(self._queue.qsize())
                except ImportError:
                    pass

        logger.info("摘要 Worker 已停止")

    async def _process_request(self, request: SummarizationRequest) -> None:
        """处理单个摘要请求。

        Args:
            request: 摘要请求
        """
        from src.database.async_session import get_async_session_maker
        from src.summarization.domain.models import PromptConfig
        from src.summarization.infrastructure.repository import (
            SummarizationRepository,
        )
        from src.summarization.llm.config import LLMProviderConfig
        from src.summarization.services.summarization_service import (
            create_summarization_service,
        )

        logger.info(
            f"Worker 开始处理: {len(request.tweet_ids)} 条推文, "
            f"source={request.source}, retry={request.retry_count}"
        )

        # 更新任务状态为运行中
        if request.task_id:
            try:
                self._registry.update_task_status(
                    request.task_id, TaskStatus.RUNNING
                )
            except Exception:
                pass  # 任务状态更新失败不影响处理

        session_maker = get_async_session_maker()
        async with session_maker() as session:
            repository = SummarizationRepository(session)
            config = LLMProviderConfig.from_env()
            service = create_summarization_service(
                repository=repository,
                config=config,
                prompt_config=PromptConfig(),
            )

            result = await service.summarize_tweets(
                tweet_ids=request.tweet_ids,
                force_refresh=request.force_refresh,
            )

            from returns.result import Failure

            if isinstance(result, Failure):
                error = result.failure()
                raise error

            summary_result = result.unwrap()

            # 更新任务状态为完成
            if request.task_id:
                self._registry.update_task_status(
                    request.task_id,
                    TaskStatus.COMPLETED,
                    result={
                        "total_tweets": summary_result.total_tweets,
                        "total_groups": summary_result.total_groups,
                        "cache_hits": summary_result.cache_hits,
                        "cache_misses": summary_result.cache_misses,
                        "total_tokens": summary_result.total_tokens,
                        "total_cost_usd": summary_result.total_cost_usd,
                        "providers_used": summary_result.providers_used,
                        "processing_time_ms": summary_result.processing_time_ms,
                    },
                )

            # 安全兜底 commit
            await session.commit()

            logger.info(
                f"Worker 处理完成: {summary_result.total_tweets} 条推文, "
                f"{summary_result.total_groups} 个组, "
                f"缓存命中 {summary_result.cache_hits}, "
                f"成本 ${summary_result.total_cost_usd:.4f}"
            )

        # 更新 Prometheus 指标
        try:
            from src.monitoring.metrics import (
                summarization_queue_processed_total,
            )

            summarization_queue_processed_total.labels(status="success").inc()
        except ImportError:
            pass

    async def _handle_failure(
        self, request: SummarizationRequest, error: Exception
    ) -> None:
        """处理失败请求的重试逻辑。

        Args:
            request: 失败的请求
            error: 异常
        """
        # 更新 Prometheus 指标
        try:
            from src.monitoring.metrics import (
                summarization_queue_processed_total,
            )

            summarization_queue_processed_total.labels(status="failure").inc()
        except ImportError:
            pass

        if request.retry_count < self.MAX_RETRY_COUNT:
            delay = self.RETRY_BASE_DELAY * (2**request.retry_count)
            logger.warning(
                f"摘要请求失败 (retry={request.retry_count}/{self.MAX_RETRY_COUNT}), "
                f"{delay:.0f}秒后重试: {error}"
            )

            # 指数退避等待
            await asyncio.sleep(delay)

            # 重新入队（低优先级）
            retry_request = SummarizationRequest(
                priority=SummarizationPriority.LOW.value,
                tweet_ids=request.tweet_ids,
                force_refresh=request.force_refresh,
                source="retry",
                task_id=request.task_id,
                retry_count=request.retry_count + 1,
            )
            try:
                self._queue.put_nowait(retry_request)
                logger.info(
                    f"重试请求已入队: {len(request.tweet_ids)} 条推文, "
                    f"retry={retry_request.retry_count}"
                )
            except asyncio.QueueFull:
                logger.error(
                    f"重试入队失败（队列满），放弃 {len(request.tweet_ids)} 条推文"
                )
                if request.task_id:
                    self._registry.update_task_status(
                        request.task_id,
                        TaskStatus.FAILED,
                        error=f"重试入队失败（队列满）: {error}",
                    )
        else:
            logger.error(
                f"摘要请求达到最大重试次数 ({self.MAX_RETRY_COUNT}), "
                f"放弃 {len(request.tweet_ids)} 条推文: {error}"
            )
            if request.task_id:
                self._registry.update_task_status(
                    request.task_id,
                    TaskStatus.FAILED,
                    error=f"达到最大重试次数: {error}",
                )
