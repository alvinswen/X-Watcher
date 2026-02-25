"""MCP 服务轻量级生命周期管理。

仅初始化数据库（建表 + 迁移），不启动调度器和摘要队列。
"""

import logging
import sys

from src.logging_config import setup_logging

logger = logging.getLogger(__name__)


def init_mcp_logging(*, stderr_only: bool = True) -> None:
    """为 MCP 模式配置日志。

    Args:
        stderr_only: stdio 传输时必须为 True，避免 stdout 输出破坏 JSON-RPC 协议。
    """
    from src.config import get_settings

    settings = get_settings()

    if stderr_only:
        # stdio 模式：禁用文件日志，仅 stderr 输出
        setup_logging(
            level=settings.log_level,
            log_format="text",
            log_file=None,
        )
        # 确保 root logger 的所有 StreamHandler 都指向 stderr
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.stream = sys.stderr
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

    # 创建所有表
    Base.metadata.create_all(eng)
    logger.info("数据库表已创建/验证")

    # 迁移：确保 is_enabled 列存在
    try:
        with eng.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE scraper_schedule_config "
                    "ADD COLUMN is_enabled BOOLEAN NOT NULL DEFAULT 1"
                )
            )
            conn.commit()
            logger.info("数据库迁移：已添加 scraper_schedule_config.is_enabled 列")
    except Exception:
        pass  # 列已存在

    # 迁移：确保 scheduler_execution_log 表存在
    try:
        with eng.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS scheduler_execution_log ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "job_id VARCHAR(100) NOT NULL,"
                    "event_type VARCHAR(20) NOT NULL,"
                    "executed_at DATETIME NOT NULL,"
                    "duration_seconds FLOAT,"
                    "error_type VARCHAR(200),"
                    "error_message TEXT,"
                    "next_run_time DATETIME,"
                    "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
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

    logger.info("MCP 数据库初始化完成")
