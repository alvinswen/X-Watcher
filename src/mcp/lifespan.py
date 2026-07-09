"""MCP 服务轻量级生命周期管理。

仅初始化数据库，不启动后台队列。
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


def init_database() -> None:
    """初始化数据库：建表。

    从 src/main.py 的 lifespan() 中提取的 DB 初始化逻辑，
    不启动 CORS/SPA 中间件。

    file 模式(pg 下线守卫):整体早返——跳过 create_all + async engine 预热。
    预热仅为 stdio 模式 stdout handler 副作用注册,
    file 模式不使用 pg async engine,无需预热(不连 pg)。
    """
    from src.data_layer.provider import is_file_mode

    if is_file_mode():
        logger.info("file 模式:跳过 MCP init_database(create_all + async engine 预热,pg 下线守卫)")
        return

    from src.database.models import Base, get_engine

    # 确保所有 ORM 模型在 create_all 前已注册到 Base.metadata
    from src.database.x_user_profile_model import XUserProfileOrm  # noqa: F401
    from src.scraper.infrastructure.article_models import ArticleOrm  # noqa: F401
    from src.scraper.infrastructure.models import TweetOrm  # noqa: F401
    from src.summarization.infrastructure.models import SummaryOrm  # noqa: F401

    eng = get_engine()

    # 引擎创建时 echo=True 会添加指向 stdout 的 handler，立即重定向
    if _stdio_mode:
        _redirect_all_handlers_to_stderr()

    # 创建所有表
    Base.metadata.create_all(eng)
    logger.info("数据库表已创建/验证")

    logger.info("MCP 数据库初始化完成")
