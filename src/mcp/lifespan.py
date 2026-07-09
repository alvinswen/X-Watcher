"""MCP 服务轻量级生命周期管理。

仅初始化日志，不启动后台队列。
"""

import logging
import sys

from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

# 是否处于 stdio 模式（需要保护 stdout 不被污染）
_stdio_mode = False


def _redirect_all_handlers_to_stderr() -> None:
    """将所有 logger 的 StreamHandler 重定向到 stderr。

    SQLAlchemy 的 echo=True 会为引擎实例 logger 添加指向 stdout 的 handler，
    这会破坏 MCP stdio 协议。此函数遍历所有已注册 logger 并统一重定向。
    """
    for name in list(logging.Logger.manager.loggerDict):
        lg = logging.getLogger(name)
        for handler in getattr(lg, "handlers", []):
            if isinstance(handler, logging.StreamHandler) and handler.stream is not sys.stderr:
                handler.stream = sys.stderr


def init_mcp_logging(*, stderr_only: bool = True) -> None:
    """为 MCP 模式配置日志。

    Args:
        stderr_only: stdio 传输时必须为 True，避免 stdout 输出破坏 JSON-RPC 协议。
    """
    from src.config import get_settings

    settings = get_settings()

    global _stdio_mode
    if stderr_only:
        _stdio_mode = True
        # stdio 模式：禁用文件日志，仅 stderr 输出
        setup_logging(
            level=settings.log_level,
            log_format="text",
            log_file=None,
        )
        _redirect_all_handlers_to_stderr()
    else:
        # SSE 模式：正常日志配置
        setup_logging(
            level=settings.log_level,
            log_format=settings.log_format,
            log_file=settings.log_file or None,
            log_file_max_bytes=settings.log_file_max_bytes,
            log_file_backup_count=settings.log_file_backup_count,
        )
