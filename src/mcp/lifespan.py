"""MCP 服务轻量级生命周期管理。

仅初始化数据库（建表 + 迁移），不启动调度器和摘要队列。
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
    """初始化数据库：建表 + 迁移。

    从 src/main.py 的 lifespan() 中提取的 DB 初始化逻辑，
    不启动 APScheduler、SummarizationQueue、CORS/SPA 中间件。
    """
    from sqlalchemy import text

    from src.database.models import Base, get_engine

    # 确保所有 ORM 模型在 create_all 前已注册到 Base.metadata
    from src.scraper.infrastructure.article_models import ArticleOrm  # noqa: F401
    from src.scraper.infrastructure.models import TweetOrm  # noqa: F401
    from src.summarization.infrastructure.models import SummaryOrm  # noqa: F401
    from src.topic.infrastructure.models import (  # noqa: F401
        TopicAccountOrm,
        TopicOrm,
        TopicSummaryTaskOrm,
    )
    from src.database.x_user_profile_model import XUserProfileOrm  # noqa: F401

    eng = get_engine()

    # 引擎创建时 echo=True 会添加指向 stdout 的 handler，立即重定向
    if _stdio_mode:
        _redirect_all_handlers_to_stderr()

    # 创建所有表
    Base.metadata.create_all(eng)
    logger.info("数据库表已创建/验证")

    # 迁移：确保 is_enabled 列存在
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(eng)

    try:
        columns = [c["name"] for c in inspector.get_columns("scraper_schedule_config")]
        if "is_enabled" not in columns:
            with eng.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE scraper_schedule_config "
                        "ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT TRUE"
                    )
                )
                conn.commit()
                logger.info("数据库迁移：已添加 scraper_schedule_config.is_enabled 列")
    except Exception:
        pass  # 表不存在

    # 迁移：确保 scheduler_execution_log 表存在
    if "scheduler_execution_log" not in inspector.get_table_names():
        table = Base.metadata.tables.get("scheduler_execution_log")
        if table is not None:
            table.create(eng, checkfirst=True)
            logger.info("数据库迁移：已创建 scheduler_execution_log 表")
        else:
            from src.database.dialect import is_sqlite

            if is_sqlite():
                pk_clause = "id INTEGER PRIMARY KEY AUTOINCREMENT"
            else:
                pk_clause = "id SERIAL PRIMARY KEY"

            try:
                with eng.connect() as conn:
                    conn.execute(
                        text(
                            f"CREATE TABLE IF NOT EXISTS scheduler_execution_log ("
                            f"{pk_clause},"
                            f"job_id VARCHAR(100) NOT NULL,"
                            f"event_type VARCHAR(20) NOT NULL,"
                            f"executed_at TIMESTAMP NOT NULL,"
                            f"duration_seconds FLOAT,"
                            f"error_type VARCHAR(200),"
                            f"error_message TEXT,"
                            f"next_run_time TIMESTAMP,"
                            f"created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                            f")"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_scheduler_log_job_id "
                            "ON scheduler_execution_log(job_id)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_scheduler_log_event_type "
                            "ON scheduler_execution_log(event_type)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_scheduler_log_executed_at "
                            "ON scheduler_execution_log(executed_at)"
                        )
                    )
                    conn.commit()
            except Exception:
                pass

    # 引擎创建后，SQLAlchemy echo=True 可能新增了 stdout handler，需再次重定向
    if _stdio_mode:
        _redirect_all_handlers_to_stderr()

    logger.info("MCP 数据库初始化完成")
