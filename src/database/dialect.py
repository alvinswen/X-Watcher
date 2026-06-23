"""数据库方言检测模块。

根据 DATABASE_URL 判断当前使用的数据库类型，并提供方言兼容的 SQL 表达式工厂函数。
"""

from __future__ import annotations

import os

from sqlalchemy import Integer, cast, extract, func, literal_column
from sqlalchemy.types import Date

from src.config import get_settings


def is_sqlite() -> bool:
    """当前是否使用 SQLite 数据库。"""
    return get_settings().database_url.startswith("sqlite")


def is_postgres() -> bool:
    """当前是否使用 PostgreSQL 数据库。"""
    url = get_settings().database_url
    return url.startswith("postgresql") or url.startswith("postgres")


# ---------------------------------------------------------------------------
# 方言兼容 SQL 表达式工厂
# ---------------------------------------------------------------------------
#
# 所有工厂函数接受可选的 bind 参数（AsyncSession / AsyncEngine / Engine），
# 优先从 bind 的实际 dialect 判断数据库类型，避免测试环境中
# settings.DATABASE_URL 与实际引擎不一致的问题。

_STRFTIME_TO_PG: dict[str, str] = {
    "%Y": "YYYY",
    "%m": "MM",
    "%d": "DD",
    "%H": "HH24",
    "%M": "MI",
    "%S": "SS",
}


def _detect_sqlite(bind=None) -> bool:
    """从 bind（Session/Engine）的 dialect 检测是否为 SQLite，否则回退到 settings。"""
    if bind is not None:
        engine = getattr(bind, "bind", bind)
        if engine is not None:
            dialect = getattr(engine, "dialect", None)
            if dialect is not None:
                return dialect.name == "sqlite"
    return is_sqlite()


def _to_pg_format(py_fmt: str) -> str:
    """将 Python strftime 格式串转为 PostgreSQL TO_CHAR 格式串。"""
    result = py_fmt
    for k, v in _STRFTIME_TO_PG.items():
        result = result.replace(k, v)
    return result


def sql_epoch(col, *, bind=None):
    """返回列的 Unix epoch 整数表达式。

    SQLite:  CAST(strftime('%s', col) AS INTEGER)
    PG:      CAST(EXTRACT(EPOCH FROM col) AS INTEGER)
    """
    if _detect_sqlite(bind):
        return cast(func.strftime("%s", col), Integer)
    return cast(extract("epoch", col), Integer)


def sql_extract_hour(col, *, bind=None):
    """返回列的小时 (0-23) 整数表达式。

    SQLite:  CAST(strftime('%H', col) AS INTEGER)
    PG:      CAST(EXTRACT(HOUR FROM col) AS INTEGER)
    """
    if _detect_sqlite(bind):
        return cast(func.strftime("%H", col), Integer)
    return cast(extract("hour", col), Integer)


def sql_epoch_to_formatted(epoch_int, fmt: str = "%Y-%m-%d %H:%M", *, bind=None):
    """将 Unix epoch 整数格式化为字符串。

    SQLite:  strftime(fmt, epoch_int, 'unixepoch')
    PG:      TO_CHAR(TO_TIMESTAMP(epoch_int), pg_fmt)
    """
    if _detect_sqlite(bind):
        return func.strftime(fmt, epoch_int, "unixepoch")
    return func.to_char(func.to_timestamp(epoch_int), _to_pg_format(fmt))


def sql_epoch_with_offset(col, minutes: int, *, bind=None):
    """返回列加偏移后的 Unix epoch 整数表达式。

    SQLite:  CAST(strftime('%s', col, 'N minutes') AS INTEGER)
    PG:      CAST(EXTRACT(EPOCH FROM col + INTERVAL 'N minutes') AS INTEGER)
    """
    if _detect_sqlite(bind):
        return cast(func.strftime("%s", col, f"{minutes} minutes"), Integer)
    return cast(
        extract("epoch", col + literal_column(f"INTERVAL '{minutes} minutes'")),
        Integer,
    )


def sql_date_with_offset(col, minutes: int, *, bind=None):
    """返回列加偏移后的日期表达式。

    SQLite:  date(col, 'N minutes')
    PG:      CAST((col + INTERVAL 'N minutes') AS DATE)
    """
    if _detect_sqlite(bind):
        return func.date(col, f"{minutes} minutes")
    return cast(
        col + literal_column(f"INTERVAL '{minutes} minutes'"), Date
    )


def get_database_size_mb() -> float | None:
    """获取当前数据库大小（MB）。

    file 模式(pg 下线守卫):递归 sum data_root 目录体积,不连 pg。
    SQLite 读文件大小,PostgreSQL 用 pg_database_size()。
    """
    from src.data_layer.provider import data_root, is_file_mode

    if is_file_mode():
        root = data_root()
        if not root.exists():
            return None
        try:
            total = sum(
                p.stat().st_size for p in root.rglob("*") if p.is_file()
            )
            return round(total / (1024 * 1024), 2)
        except OSError:
            return None

    settings = get_settings()
    db_url = settings.database_url
    if is_sqlite():
        db_path = db_url.replace("sqlite:///", "")
        if db_path.startswith("./"):
            db_path = db_path[2:]
        try:
            return round(os.path.getsize(db_path) / (1024 * 1024), 2)
        except OSError:
            return None
    elif is_postgres():
        from sqlalchemy import text

        from src.database.models import get_engine

        try:
            with get_engine().connect() as conn:
                result = conn.execute(
                    text("SELECT pg_database_size(current_database())")
                )
                size_bytes = result.scalar()
                return round(size_bytes / (1024 * 1024), 2) if size_bytes else None
        except Exception:
            return None
    return None
