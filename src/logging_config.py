"""日志配置模块。

提供结构化日志格式器、trace_id 链路追踪和文件轮转支持。

双输出策略：
- 控制台：增强文本格式（包含 trace_id 和关键 extra 字段）
- 文件：JSON 格式（机器可解析，支持 grep/jq 查询）

文件写入通过 QueueHandler + QueueListener 异步串行化，
避免 Windows 上 RotatingFileHandler.doRollover() 的文件锁冲突（WinError 32）。
"""

import atexit
import contextvars
import json
import logging
import os
import queue
from datetime import datetime, timezone
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from typing import Any

# ── trace_id 上下文变量 ─────────────────────────────────────────
# 在管道入口（抓取/摘要任务）设置，自动传播到所有下游日志
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)

# ── 全局 QueueListener 引用（用于 shutdown 清理） ──────────────────
_queue_listener: QueueListener | None = None

# ── 预定义的有意义 extra 键 ──────────────────────────────────────
# 在增强文本格式中只输出这些键，避免打印 Python 内部属性
_DISPLAY_EXTRA_KEYS = frozenset({
    "trace_id",
    "task_id",
    "tweet_id",
    "provider",
    "model",
    "tokens",
    "cost_usd",
    "error_type",
    "error_message",
    "source",
    "event",
    "cache_hits",
    "cache_misses",
    "total_tweets",
    "processing_time_ms",
    "retry_attempt",
    "wait_seconds",
    "chunk_index",
    "total_chunks",
    "enqueue_method",
})

# 标准 LogRecord 属性（用于过滤 extra 字段）
_STANDARD_RECORD_ATTRS: frozenset[str] | None = None


def _get_standard_record_attrs() -> frozenset[str]:
    """获取标准 LogRecord 属性集合（懒初始化）。"""
    global _STANDARD_RECORD_ATTRS
    if _STANDARD_RECORD_ATTRS is None:
        dummy = logging.LogRecord("", 0, "", 0, "", (), None)
        _STANDARD_RECORD_ATTRS = frozenset(dummy.__dict__.keys()) | {
            "message", "msg", "args",
        }
    return _STANDARD_RECORD_ATTRS


def _extract_extra(record: logging.LogRecord) -> dict[str, Any]:
    """从 LogRecord 中提取 extra 字段。"""
    standard = _get_standard_record_attrs()
    return {
        k: v for k, v in record.__dict__.items()
        if k not in standard
    }


# ── TraceIdFilter ───────────────────────────────────────────────

class TraceIdFilter(logging.Filter):
    """自动注入 trace_id 到每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get() or "-"
        return True


# ── JSON 格式器 ─────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """JSON 结构化日志格式器。

    输出包含 timestamp、level、logger、message、trace_id 和所有 extra 字段。
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }

        # 收集所有 extra 字段
        extra = _extract_extra(record)
        if extra:
            log_entry["extra"] = extra

        # 异常信息
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ── 增强文本格式器 ──────────────────────────────────────────────

class EnhancedTextFormatter(logging.Formatter):
    """增强文本格式器。

    在标准文本输出后追加关键 extra 字段，格式：
    {timestamp} {level} [{trace_id}] {logger}: {message} | key1=val1 key2=val2
    """

    def format(self, record: logging.LogRecord) -> str:
        # 基础格式
        timestamp = self.formatTime(record, self.datefmt)
        trace_id = getattr(record, "trace_id", "-")
        level = record.levelname.ljust(5)
        message = record.getMessage()

        base = f"{timestamp} {level} [{trace_id}] {record.name}: {message}"

        # 追加有意义的 extra 字段
        extra = _extract_extra(record)
        display_parts = []
        for key in _DISPLAY_EXTRA_KEYS:
            if key in extra and key != "trace_id":
                val = extra[key]
                if isinstance(val, float):
                    display_parts.append(f"{key}={val:.4f}")
                else:
                    display_parts.append(f"{key}={val}")

        if display_parts:
            base += " | " + " ".join(display_parts)

        # 异常信息
        if record.exc_info and record.exc_info[1]:
            base += "\n" + self.formatException(record.exc_info)

        return base


# ── shutdown_logging ─────────────────────────────────────────────

def shutdown_logging() -> None:
    """停止 QueueListener 并刷新所有日志。

    由 atexit 自动调用，也可手动调用。
    幂等：多次调用安全。
    """
    global _queue_listener
    if _queue_listener is not None:
        _queue_listener.stop()
        # QueueListener.stop() 不关闭底层 handler，需要显式关闭
        # 以释放文件锁（Windows 上必要，否则临时文件无法删除）
        for handler in _queue_listener.handlers:
            handler.close()
        _queue_listener = None


# ── setup_logging ───────────────────────────────────────────────

def setup_logging(
    *,
    level: str = "INFO",
    log_format: str = "text",
    log_file: str | None = "logs/x-watcher.log",
    log_file_max_bytes: int = 50 * 1024 * 1024,
    log_file_backup_count: int = 5,
) -> None:
    """配置应用日志系统。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        log_format: 控制台日志格式（"text" 或 "json"）
        log_file: 日志文件路径（None 禁用文件输出）
        log_file_max_bytes: 单个日志文件最大字节数
        log_file_backup_count: 日志文件备份数量
    """
    global _queue_listener

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 停止旧的 QueueListener（如果存在，避免重复调用泄漏线程）
    if _queue_listener is not None:
        _queue_listener.stop()
        for handler in _queue_listener.handlers:
            handler.close()
        _queue_listener = None

    # 清除已有 handler（避免重复配置）
    root.handlers.clear()

    # 添加 trace_id 过滤器到 root
    trace_filter = TraceIdFilter()
    root.addFilter(trace_filter)

    # ── 控制台 handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(root.level)
    console_handler.addFilter(trace_filter)

    if log_format == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(
            EnhancedTextFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        )

    root.addHandler(console_handler)

    # ── 文件 handler（始终 JSON 格式，通过 QueueHandler + QueueListener 异步写入） ──
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=log_file_max_bytes,
            backupCount=log_file_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(root.level)
        file_handler.setFormatter(JSONFormatter())
        # 注意：不需要给 file_handler 加 TraceIdFilter，
        # 因为 root logger 的 TraceIdFilter 在 QueueHandler.emit() 之前已运行，
        # record.trace_id 已被填充。

        log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
        queue_handler = QueueHandler(log_queue)
        queue_handler.setLevel(root.level)
        queue_handler.addFilter(trace_filter)
        root.addHandler(queue_handler)

        _queue_listener = QueueListener(
            log_queue, file_handler, respect_handler_level=True
        )
        _queue_listener.start()

        atexit.register(shutdown_logging)
