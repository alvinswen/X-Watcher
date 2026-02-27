"""每日摘要工作流相关功能测试。

测试 get_topic_summary deadline 参数、manage_scheduler last_execution、
recipes 资源注册和内容。
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _get_tool_funcs():
    """通过 FastMCP 实例获取注册的工具函数。"""
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    tools = mcp._tool_manager._tools
    return {name: tool.fn for name, tool in tools.items()}


def _get_resource_funcs():
    """通过 FastMCP 实例获取注册的资源函数。"""
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    resources = mcp._resource_manager._resources
    return {str(uri): res.fn for uri, res in resources.items()}


@pytest.fixture
def tool_funcs():
    return _get_tool_funcs()


@pytest.fixture
def resource_funcs():
    return _get_resource_funcs()


def _mock_session_maker(mock_session):
    sm = MagicMock()
    sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    sm.return_value.__aexit__ = AsyncMock(return_value=False)
    return sm


# ── get_topic_summary deadline 参数测试 ───────────────────────────


class TestGetTopicSummaryDeadline:
    @pytest.mark.asyncio
    async def test_create_with_custom_deadline(self, tool_funcs):
        """传入自定义 deadline 字符串，验证解析和传递正确。"""
        mock_task = MagicMock()
        mock_task.model_dump.return_value = {
            "id": 1,
            "topic_id": 1,
            "status": "pending",
        }

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)
        mock_service = MagicMock()
        mock_service.create_and_execute_task = AsyncMock(return_value=mock_task)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.topic.services.topic_summary_service.TopicSummaryService.get_instance",
                return_value=mock_service,
            ),
        ):
            result = await tool_funcs["get_topic_summary"](
                topic_id=1,
                action="create",
                time_span_hours=24,
                deadline="2026-02-26T10:00:00Z",
                tz_offset=-480,
            )

        data = json.loads(result)
        assert data["success"] is True

        # 验证传给 service 的 deadline 是解析后的 datetime
        call_kwargs = mock_service.create_and_execute_task.call_args.kwargs
        expected_deadline = datetime(2026, 2, 26, 10, 0, 0, tzinfo=timezone.utc)
        assert call_kwargs["deadline"] == expected_deadline

    @pytest.mark.asyncio
    async def test_create_without_deadline_uses_now(self, tool_funcs):
        """不传 deadline，验证默认使用 now()。"""
        mock_task = MagicMock()
        mock_task.model_dump.return_value = {
            "id": 1,
            "topic_id": 1,
            "status": "pending",
        }

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)
        mock_service = MagicMock()
        mock_service.create_and_execute_task = AsyncMock(return_value=mock_task)

        fake_now = datetime(2026, 2, 27, 5, 30, 0, tzinfo=timezone.utc)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.topic.services.topic_summary_service.TopicSummaryService.get_instance",
                return_value=mock_service,
            ),
            patch(
                "src.mcp.tools.topic_tools.datetime",
            ) as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await tool_funcs["get_topic_summary"](
                topic_id=1,
                action="create",
            )

        data = json.loads(result)
        assert data["success"] is True

        call_kwargs = mock_service.create_and_execute_task.call_args.kwargs
        assert call_kwargs["deadline"] == fake_now

    @pytest.mark.asyncio
    async def test_create_with_invalid_deadline(self, tool_funcs):
        """传入非法 deadline 格式，验证返回错误。"""
        result = await tool_funcs["get_topic_summary"](
            topic_id=1,
            action="create",
            deadline="not-a-valid-date",
        )
        data = json.loads(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_deadline_ignored_for_latest_action(self, tool_funcs):
        """action=latest 时 deadline 参数不影响行为。"""
        mock_task = MagicMock()
        mock_task.model_dump.return_value = {"id": 1, "content": "summary text"}

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)
        mock_service = MagicMock()
        mock_service.get_latest_summary = AsyncMock(return_value=mock_task)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.topic.services.topic_summary_service.TopicSummaryService.get_instance",
                return_value=mock_service,
            ),
        ):
            result = await tool_funcs["get_topic_summary"](
                topic_id=1,
                action="latest",
                deadline="2026-02-26T10:00:00Z",
            )

        data = json.loads(result)
        assert data["success"] is True


# ── manage_scheduler last_execution 测试 ──────────────────────────


class TestManageSchedulerLastExecution:
    @pytest.mark.asyncio
    async def test_status_includes_last_execution(self, tool_funcs):
        """验证 status 响应中包含 last_execution 字段。"""
        mock_config = MagicMock()
        mock_config.interval_seconds = 1800
        mock_config.is_enabled = True
        mock_config.next_run_time = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)
        mock_config.updated_at = datetime(2026, 2, 27, 10, 0, tzinfo=timezone.utc)
        mock_config.updated_by = "mcp_admin"

        from src.scraper.domain.scheduler_log import (
            SchedulerEventType,
            SchedulerExecutionLog,
        )

        mock_log = SchedulerExecutionLog(
            id=1,
            job_id="scrape_all",
            event_type=SchedulerEventType.EXECUTED,
            executed_at=datetime(2026, 2, 27, 10, 30, 0, tzinfo=timezone.utc),
            duration_seconds=120.5,
        )

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)
        mock_repo = MagicMock()
        mock_repo.get_recent_logs = AsyncMock(return_value=[mock_log])

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.preference.services.schedule_service.ScraperScheduleService.get_schedule_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.scraper.infrastructure.scheduler_log_repository.SchedulerExecutionLogRepository",
                return_value=mock_repo,
            ),
        ):
            result = await tool_funcs["manage_scheduler"](action="status")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["last_execution"] is not None
        assert data["data"]["last_execution"]["event_type"] == "executed"
        assert data["data"]["last_execution"]["duration_seconds"] == 120.5

    @pytest.mark.asyncio
    async def test_status_last_execution_none_when_no_logs(self, tool_funcs):
        """无执行记录时 last_execution 为 None。"""
        mock_config = MagicMock()
        mock_config.interval_seconds = 1800
        mock_config.is_enabled = True
        mock_config.next_run_time = None
        mock_config.updated_at = None
        mock_config.updated_by = None

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)
        mock_repo = MagicMock()
        mock_repo.get_recent_logs = AsyncMock(return_value=[])

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.preference.services.schedule_service.ScraperScheduleService.get_schedule_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.scraper.infrastructure.scheduler_log_repository.SchedulerExecutionLogRepository",
                return_value=mock_repo,
            ),
        ):
            result = await tool_funcs["manage_scheduler"](action="status")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["last_execution"] is None

    @pytest.mark.asyncio
    async def test_status_last_execution_graceful_on_error(self, tool_funcs):
        """查询执行记录出错时 last_execution 为 None，不影响整体响应。"""
        mock_config = MagicMock()
        mock_config.interval_seconds = 1800
        mock_config.is_enabled = True
        mock_config.next_run_time = None
        mock_config.updated_at = None
        mock_config.updated_by = None

        mock_sm = MagicMock()
        mock_sm.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB error")
        )
        mock_sm.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.preference.services.schedule_service.ScraperScheduleService.get_schedule_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
        ):
            result = await tool_funcs["manage_scheduler"](action="status")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["last_execution"] is None


# ── recipes 资源测试 ──────────────────────────────────────────────


class TestRecipesResource:
    def test_recipe_resource_registered(self):
        """验证 daily-summary recipe 资源已注册。"""
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        resource_uris = set(mcp._resource_manager._resources.keys())
        assert "xwatcher://recipes/daily-summary" in resource_uris

    @pytest.mark.asyncio
    async def test_recipe_content(self, resource_funcs):
        """验证配方内容包含关键段落。"""
        recipe_fn = resource_funcs["xwatcher://recipes/daily-summary"]
        content = await recipe_fn()
        assert "每日摘要生成工作流" in content
        assert "Step 1" in content
        assert "Step 7" in content
        assert "manage_scheduler" in content
        assert "get_topic_summary" in content
        assert "trigger_scrape" in content

    def test_instructions_mention_recipes(self):
        """验证 server instructions 中提及了工作流配方。"""
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        assert "xwatcher://recipes/daily-summary" in mcp.instructions


# ── batch_summarize backfill 修复测试 ────────────────────────────


class TestBatchSummarizeBackfill:
    """验证 backfill action 正确调用 SummarizationQueue.enqueue。"""

    @pytest.mark.asyncio
    async def test_backfill_calls_enqueue_correctly(self, tool_funcs):
        """验证 backfill 调用 enqueue（而非 enqueue_batch），参数类型正确。"""
        from src.summarization.services.summarization_queue import (
            SummarizationPriority,
        )

        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value="task-abc-123")

        mock_session = AsyncMock()
        # 模拟查询返回待摘要推文 ID
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("tw1",), ("tw2",), ("tw3",)]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.summarization.services.summarization_queue.SummarizationQueue.get_instance",
                return_value=mock_queue,
            ),
        ):
            result = await tool_funcs["batch_summarize"](
                action="backfill",
                since="2026-02-26T00:00:00Z",
                until="2026-02-27T00:00:00Z",
                batch_size=50,
            )

        data = json.loads(result)
        assert data["success"] is True

        # 验证调用的是 enqueue 而不是 enqueue_batch
        mock_queue.enqueue.assert_called_once()
        call_kwargs = mock_queue.enqueue.call_args
        assert call_kwargs[0][0] == ["tw1", "tw2", "tw3"]  # tweet_ids
        assert call_kwargs[1]["source"] == "mcp_backfill"
        assert call_kwargs[1]["priority"] == SummarizationPriority.HIGH

    @pytest.mark.asyncio
    async def test_backfill_starts_queue_before_enqueue(self, tool_funcs):
        """验证 backfill 在入队前调用了 queue.start()。"""
        call_order = []

        mock_queue = MagicMock()

        async def mock_start():
            call_order.append("start")

        async def mock_enqueue(*args, **kwargs):
            call_order.append("enqueue")
            return "task-xyz"

        mock_queue.start = mock_start
        mock_queue.enqueue = mock_enqueue

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("tw1",)]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.summarization.services.summarization_queue.SummarizationQueue.get_instance",
                return_value=mock_queue,
            ),
        ):
            await tool_funcs["batch_summarize"](
                action="backfill",
                since="2026-02-26T00:00:00Z",
                until="2026-02-27T00:00:00Z",
            )

        assert call_order == ["start", "enqueue"]

    @pytest.mark.asyncio
    async def test_backfill_returns_task_id(self, tool_funcs):
        """验证响应中包含 task_id 和 tweet_count，而非旧的 enqueued 计数。"""
        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value="task-return-id-456")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("tw1",), ("tw2",)]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.summarization.services.summarization_queue.SummarizationQueue.get_instance",
                return_value=mock_queue,
            ),
        ):
            result = await tool_funcs["batch_summarize"](
                action="backfill",
                since="2026-02-26T00:00:00Z",
                until="2026-02-27T00:00:00Z",
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["task_id"] == "task-return-id-456"
        assert data["data"]["tweet_count"] == 2
        assert "enqueued" not in data["data"]  # 旧字段不应存在

    @pytest.mark.asyncio
    async def test_backfill_no_pending_tweets(self, tool_funcs):
        """无待摘要推文时返回 count=0 消息，不调用 enqueue。"""
        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()
        mock_queue.enqueue = AsyncMock()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.auth.require_admin", return_value=None),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.summarization.services.summarization_queue.SummarizationQueue.get_instance",
                return_value=mock_queue,
            ),
        ):
            result = await tool_funcs["batch_summarize"](
                action="backfill",
                since="2026-02-26T00:00:00Z",
                until="2026-02-27T00:00:00Z",
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["count"] == 0
        mock_queue.enqueue.assert_not_called()
