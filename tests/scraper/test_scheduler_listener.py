"""调度器事件监听器测试。"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
)

from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog
from src.scraper.scheduler_listener import (
    _calc_duration,
    _get_next_run_time,
    scheduler_event_listener,
)


class TestCalcDuration:
    """_calc_duration 辅助函数测试。"""

    def test_calc_duration_with_scheduled_run_time(self):
        """有 scheduled_run_time 时应计算出合理的正数 duration。"""
        event = MagicMock()
        event.scheduled_run_time = datetime.now(timezone.utc)
        result = _calc_duration(event)
        assert result is not None
        assert result >= 0

    def test_calc_duration_without_scheduled_run_time(self):
        """无 scheduled_run_time 属性时返回 None。"""
        event = MagicMock(spec=[])  # 空 spec，无 scheduled_run_time
        result = _calc_duration(event)
        assert result is None

    def test_calc_duration_with_none_scheduled_run_time(self):
        """scheduled_run_time 为 None 时返回 None。"""
        event = MagicMock()
        event.scheduled_run_time = None
        result = _calc_duration(event)
        assert result is None

    def test_calc_duration_with_naive_datetime(self):
        """无时区的 scheduled_run_time 应被当作 UTC 处理，返回非 None 结果。"""
        event = MagicMock()
        # 使用 UTC 的 naive datetime 来避免时区差异导致的负值
        event.scheduled_run_time = datetime.utcnow()
        result = _calc_duration(event)
        assert result is not None
        # 由于 replace(tzinfo=utc) 处理，结果应接近 0 秒
        assert abs(result) < 5


class TestGetNextRunTime:
    """_get_next_run_time 辅助函数测试。"""

    def test_returns_none_when_scheduler_not_registered(self):
        """调度器未注册时返回 None。"""
        with patch(
            "src.scheduler_accessor.get_scheduler",
            return_value=None,
        ):
            result = _get_next_run_time("scraper_job")
            assert result is None

    def test_returns_none_when_job_not_found(self):
        """Job 不存在时返回 None。"""
        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = None
        with patch(
            "src.scheduler_accessor.get_scheduler",
            return_value=mock_scheduler,
        ):
            result = _get_next_run_time("nonexistent_job")
            assert result is None

    def test_returns_next_run_time_when_job_exists(self):
        """Job 存在时返回其 next_run_time。"""
        expected_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mock_job = MagicMock()
        mock_job.next_run_time = expected_time
        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = mock_job
        with patch(
            "src.scheduler_accessor.get_scheduler",
            return_value=mock_scheduler,
        ):
            result = _get_next_run_time("scraper_job")
            assert result == expected_time


class TestSchedulerEventListener:
    """scheduler_event_listener 主函数测试。"""

    def _make_executed_event(self):
        """创建模拟的 EVENT_JOB_EXECUTED 事件。"""
        event = MagicMock()
        event.code = EVENT_JOB_EXECUTED
        event.job_id = "scraper_job"
        event.scheduled_run_time = datetime.now(timezone.utc)
        event.retval = None
        return event

    def _make_error_event(self, exception=None):
        """创建模拟的 EVENT_JOB_ERROR 事件。"""
        event = MagicMock()
        event.code = EVENT_JOB_ERROR
        event.job_id = "scraper_job"
        event.scheduled_run_time = datetime.now(timezone.utc)
        event.exception = exception or ValueError("test error")
        event.traceback = "Traceback (most recent call last):\n  ..."
        return event

    def _make_missed_event(self):
        """创建模拟的 EVENT_JOB_MISSED 事件。"""
        event = MagicMock()
        event.code = EVENT_JOB_MISSED
        event.job_id = "scraper_job"
        event.scheduled_run_time = datetime.now(timezone.utc)
        return event

    @patch("src.scraper.scheduler_listener._update_prometheus_metrics")
    @patch("src.scraper.scheduler_listener.SchedulerExecutionLogSyncWriter.write_log")
    @patch("src.scraper.scheduler_listener._get_next_run_time", return_value=None)
    def test_listener_handles_executed_event(
        self, mock_next_run, mock_write_log, mock_metrics
    ):
        """EVENT_JOB_EXECUTED 事件应记录日志并写入 DB。"""
        event = self._make_executed_event()
        scheduler_event_listener(event)

        mock_write_log.assert_called_once()
        log_entry = mock_write_log.call_args[0][0]
        assert log_entry.job_id == "scraper_job"
        assert log_entry.event_type == SchedulerEventType.EXECUTED
        assert log_entry.duration_seconds is not None
        assert log_entry.error_type is None
        assert log_entry.error_message is None

        mock_metrics.assert_called_once_with(
            SchedulerEventType.EXECUTED, "scraper_job", log_entry.duration_seconds
        )

    @patch("src.scraper.scheduler_listener._update_prometheus_metrics")
    @patch("src.scraper.scheduler_listener.SchedulerExecutionLogSyncWriter.write_log")
    @patch("src.scraper.scheduler_listener._get_next_run_time", return_value=None)
    def test_listener_handles_error_event(
        self, mock_next_run, mock_write_log, mock_metrics
    ):
        """EVENT_JOB_ERROR 事件应记录错误详情。"""
        exception = RuntimeError("connection timeout")
        event = self._make_error_event(exception)
        scheduler_event_listener(event)

        mock_write_log.assert_called_once()
        log_entry = mock_write_log.call_args[0][0]
        assert log_entry.job_id == "scraper_job"
        assert log_entry.event_type == SchedulerEventType.ERROR
        assert log_entry.error_type == "RuntimeError"
        assert "connection timeout" in log_entry.error_message

        mock_metrics.assert_called_once()

    @patch("src.scraper.scheduler_listener._update_prometheus_metrics")
    @patch("src.scraper.scheduler_listener.SchedulerExecutionLogSyncWriter.write_log")
    @patch("src.scraper.scheduler_listener._get_next_run_time", return_value=None)
    def test_listener_handles_missed_event(
        self, mock_next_run, mock_write_log, mock_metrics
    ):
        """EVENT_JOB_MISSED 事件应记录遗漏信息。"""
        event = self._make_missed_event()
        scheduler_event_listener(event)

        mock_write_log.assert_called_once()
        log_entry = mock_write_log.call_args[0][0]
        assert log_entry.job_id == "scraper_job"
        assert log_entry.event_type == SchedulerEventType.MISSED
        assert log_entry.duration_seconds is None

        mock_metrics.assert_called_once_with(
            SchedulerEventType.MISSED, "scraper_job", None
        )

    def test_sync_writer_write_log_does_not_raise_on_db_failure(self):
        """SchedulerExecutionLogSyncWriter.write_log DB 失败时不应抛出异常。"""
        from src.scraper.infrastructure.scheduler_log_repository import (
            SchedulerExecutionLogSyncWriter,
        )

        log_entry = SchedulerExecutionLog(
            job_id="scraper_job",
            event_type=SchedulerEventType.EXECUTED,
            executed_at=datetime.now(timezone.utc),
        )

        # Mock get_engine 使其抛出异常（lazy import 路径）
        with patch(
            "src.database.models.get_engine",
            side_effect=Exception("DB connection failed"),
        ):
            # 不应抛出异常
            SchedulerExecutionLogSyncWriter.write_log(log_entry)

    @patch("src.scraper.scheduler_listener._update_prometheus_metrics")
    @patch("src.scraper.scheduler_listener.SchedulerExecutionLogSyncWriter.write_log")
    @patch("src.scraper.scheduler_listener._get_next_run_time")
    def test_listener_records_next_run_time(
        self, mock_next_run, mock_write_log, mock_metrics
    ):
        """监听器应记录下次运行时间。"""
        expected_next = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_next_run.return_value = expected_next

        event = self._make_executed_event()
        scheduler_event_listener(event)

        log_entry = mock_write_log.call_args[0][0]
        assert log_entry.next_run_time == expected_next

    @patch("src.scraper.scheduler_listener._update_prometheus_metrics")
    @patch("src.scraper.scheduler_listener.SchedulerExecutionLogSyncWriter.write_log")
    @patch("src.scraper.scheduler_listener._get_next_run_time", return_value=None)
    def test_error_message_truncated_to_2000_chars(
        self, mock_next_run, mock_write_log, mock_metrics
    ):
        """过长的错误信息应被截断至 2000 字符。"""
        long_error = "x" * 5000
        exception = RuntimeError(long_error)
        event = self._make_error_event(exception)
        scheduler_event_listener(event)

        log_entry = mock_write_log.call_args[0][0]
        assert len(log_entry.error_message) == 2000
