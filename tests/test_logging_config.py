"""日志配置模块测试。

测试 JSONFormatter、EnhancedTextFormatter、TraceIdFilter 和 setup_logging。
"""

import json
import logging
import os
import tempfile
from unittest.mock import patch

import pytest

from src.logging_config import (
    EnhancedTextFormatter,
    JSONFormatter,
    TraceIdFilter,
    setup_logging,
    trace_id_var,
)


@pytest.fixture(autouse=True)
def reset_logging():
    """每个测试后重置 logging 配置。"""
    yield
    # 关闭所有 handler（释放文件锁），然后清理
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    root.filters.clear()
    root.setLevel(logging.WARNING)
    # 重置 trace_id
    trace_id_var.set(None)


class TestTraceIdFilter:
    """测试 TraceIdFilter。"""

    def test_injects_default_trace_id(self):
        """测试默认 trace_id 为 '-'。"""
        f = TraceIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f.filter(record)
        assert record.trace_id == "-"

    def test_injects_set_trace_id(self):
        """测试注入已设置的 trace_id。"""
        trace_id_var.set("abc-123")
        f = TraceIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f.filter(record)
        assert record.trace_id == "abc-123"

    def test_always_returns_true(self):
        """测试过滤器始终返回 True（不过滤任何日志）。"""
        f = TraceIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert f.filter(record) is True


class TestJSONFormatter:
    """测试 JSONFormatter。"""

    def test_basic_format(self):
        """测试基本 JSON 输出格式。"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "test.logger", logging.INFO, "", 0, "测试消息", (), None
        )
        record.trace_id = "test-trace"

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "测试消息"
        assert data["trace_id"] == "test-trace"
        assert "timestamp" in data

    def test_extra_fields_included(self):
        """测试 extra 字段包含在 JSON 输出中。"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None
        )
        record.trace_id = "-"
        record.tweet_id = "tw_001"
        record.provider = "openrouter"

        output = formatter.format(record)
        data = json.loads(output)

        assert data["extra"]["tweet_id"] == "tw_001"
        assert data["extra"]["provider"] == "openrouter"

    def test_exception_included(self):
        """测试异常信息包含在 JSON 输出中。"""
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                "test", logging.ERROR, "", 0, "失败", (), sys.exc_info()
            )
            record.trace_id = "-"

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_ensures_ascii_false(self):
        """测试中文字符不被转义。"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "中文消息", (), None
        )
        record.trace_id = "-"

        output = formatter.format(record)
        assert "中文消息" in output
        assert "\\u" not in output


class TestEnhancedTextFormatter:
    """测试 EnhancedTextFormatter。"""

    def test_basic_format_with_trace_id(self):
        """测试包含 trace_id 的文本输出。"""
        formatter = EnhancedTextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord(
            "src.test", logging.INFO, "", 0, "测试消息", (), None
        )
        record.trace_id = "abc-123"

        output = formatter.format(record)

        assert "[abc-123]" in output
        assert "src.test" in output
        assert "测试消息" in output
        assert "INFO" in output

    def test_extra_fields_appended(self):
        """测试关键 extra 字段追加到消息后。"""
        formatter = EnhancedTextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "LLM 调用", (), None
        )
        record.trace_id = "-"
        record.provider = "openrouter"
        record.tweet_id = "tw_001"

        output = formatter.format(record)

        assert "| " in output
        assert "provider=openrouter" in output
        assert "tweet_id=tw_001" in output

    def test_no_extra_no_pipe(self):
        """测试没有 extra 字段时不显示 |。"""
        formatter = EnhancedTextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "简单消息", (), None
        )
        record.trace_id = "-"

        output = formatter.format(record)

        assert "| " not in output

    def test_float_formatting(self):
        """测试浮点数格式化为 4 位小数。"""
        formatter = EnhancedTextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "成本", (), None
        )
        record.trace_id = "-"
        record.cost_usd = 0.00123456789

        output = formatter.format(record)

        assert "cost_usd=0.0012" in output


class TestSetupLogging:
    """测试 setup_logging 函数。"""

    def test_console_handler_created(self):
        """测试控制台 handler 被创建。"""
        setup_logging(level="INFO", log_file=None)

        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)

    def test_file_handler_created(self):
        """测试文件 handler 被创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(level="INFO", log_file=log_path)

            root = logging.getLogger()
            assert len(root.handlers) == 2

            # 验证文件 handler 使用 JSON 格式
            file_handler = root.handlers[1]
            assert isinstance(file_handler.formatter, JSONFormatter)

            # Windows: 必须在 TemporaryDirectory 退出前关闭文件 handler
            for h in root.handlers[:]:
                h.close()
                root.removeHandler(h)

    def test_text_format_console(self):
        """测试文本格式控制台。"""
        setup_logging(level="INFO", log_format="text", log_file=None)

        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, EnhancedTextFormatter)

    def test_json_format_console(self):
        """测试 JSON 格式控制台。"""
        setup_logging(level="INFO", log_format="json", log_file=None)

        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_trace_id_filter_added(self):
        """测试 TraceIdFilter 被添加到 root logger。"""
        setup_logging(level="INFO", log_file=None)

        root = logging.getLogger()
        trace_filters = [f for f in root.filters if isinstance(f, TraceIdFilter)]
        assert len(trace_filters) == 1

    def test_file_output_is_json(self):
        """测试文件输出为有效 JSON 格式。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            setup_logging(level="INFO", log_file=log_path)

            # 发送一条日志
            test_logger = logging.getLogger("test.json_output")
            trace_id_var.set("integration-test")
            test_logger.info("测试消息", extra={"tweet_id": "tw_001"})

            # 读取文件并验证 JSON
            with open(log_path, encoding="utf-8") as f:
                line = f.readline().strip()

            data = json.loads(line)
            assert data["message"] == "测试消息"
            assert data["trace_id"] == "integration-test"
            assert data["extra"]["tweet_id"] == "tw_001"

            # Windows: 必须在 TemporaryDirectory 退出前关闭文件 handler
            root = logging.getLogger()
            for h in root.handlers[:]:
                h.close()
                root.removeHandler(h)

    def test_log_directory_auto_created(self):
        """测试日志目录自动创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "subdir", "nested", "test.log")
            setup_logging(level="INFO", log_file=log_path)

            assert os.path.exists(os.path.dirname(log_path))

            # Windows: 必须在 TemporaryDirectory 退出前关闭文件 handler
            root = logging.getLogger()
            for h in root.handlers[:]:
                h.close()
                root.removeHandler(h)

    def test_no_file_handler_when_none(self):
        """测试 log_file=None 时不创建文件 handler。"""
        setup_logging(level="INFO", log_file=None)

        root = logging.getLogger()
        assert len(root.handlers) == 1  # 只有控制台

    def test_level_setting(self):
        """测试日志级别正确设置。"""
        setup_logging(level="DEBUG", log_file=None)

        root = logging.getLogger()
        assert root.level == logging.DEBUG
