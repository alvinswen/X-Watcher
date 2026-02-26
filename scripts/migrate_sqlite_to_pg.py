"""SQLite → PostgreSQL 数据迁移脚本。

使用 SQLAlchemy Core 从 SQLite 读取数据，批量写入 PostgreSQL。
按外键依赖顺序迁移，迁移后重置 PostgreSQL SERIAL 序列。

用法:
    DATABASE_URL=postgresql://xwatcher:changeme@localhost:5432/xwatcher \
      python scripts/migrate_sqlite_to_pg.py [--sqlite-path ./news_agent.db] [--batch-size 500]
"""

import argparse
import sys
import os
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.types import Boolean, DateTime


# 按外键依赖排序的迁移顺序
MIGRATION_ORDER = [
    # 独立表（无外键依赖）
    "users",
    "scraper_follows",
    "scraper_schedule_config",
    "scraper_fetch_stats",
    "x_user_profiles",
    "tweets",
    "scheduler_execution_log",
    "task_execution_log",
    "clustering_runs",
    "articles",
    # 有外键依赖的表
    "api_keys",           # FK → users
    "news_items",         # FK → users
    "summaries",          # FK → tweets
    "topics",             # FK → users (nullable)
    "topic_accounts",     # FK → topics
    "topic_summary_tasks",  # FK → topics
    "topic_summaries",    # FK → topic_summary_tasks
    "cluster_assignments",  # FK → clustering_runs
]

# 跳过的表（PostgreSQL 中不存在或已处理）
SKIP_TABLES = {"alembic_version", "preferences"}

# 有 SERIAL 自增列的表及其列名
SERIAL_COLUMNS = {
    "users": "id",
    "api_keys": "id",
    "news_items": "id",
    "scraper_follows": "id",
    "scraper_schedule_config": "id",
    "scheduler_execution_log": "id",
    "task_execution_log": "id",
    "topics": "id",
    "topic_accounts": "id",
    "topic_summary_tasks": "id",
    "topic_summaries": "id",
    "clustering_runs": "id",
    "cluster_assignments": "id",
}


def _convert_value(value, pg_type):
    """根据 PostgreSQL 列类型转换 SQLite 值。"""
    if value is None:
        return None
    # SQLite 存 0/1，PostgreSQL 需要 True/False
    if isinstance(pg_type, Boolean):
        return bool(value)
    # SQLite 存字符串时间戳，PostgreSQL 需要 datetime 对象
    if isinstance(pg_type, DateTime) and isinstance(value, str):
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        # 无法解析，返回原值让 PG 尝试
        return value
    return value


def migrate_table(sqlite_conn, pg_conn, table_name: str, batch_size: int) -> int:
    """迁移单张表的数据。返回迁移的行数。"""
    # 读取 SQLite 数据
    result = sqlite_conn.execute(text(f"SELECT * FROM [{table_name}]"))
    columns = list(result.keys())
    rows = result.fetchall()

    if not rows:
        return 0

    # 获取 PostgreSQL 表的列信息（名称 + 类型）
    pg_inspector = inspect(pg_conn)
    pg_col_info = {col["name"]: col["type"] for col in pg_inspector.get_columns(table_name)}
    valid_columns = [c for c in columns if c in pg_col_info]

    if not valid_columns:
        print(f"  WARNING: No matching columns for {table_name}")
        return 0

    # 构建参数化 INSERT
    col_list = ", ".join(f'"{c}"' for c in valid_columns)
    param_list = ", ".join(f":{c}" for c in valid_columns)
    insert_sql = text(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({param_list})')

    # 批量插入（带类型转换）
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        batch_dicts = []
        for row in batch:
            row_dict = {}
            for col_idx, col_name in enumerate(columns):
                if col_name in pg_col_info:
                    row_dict[col_name] = _convert_value(
                        row[col_idx], pg_col_info[col_name]
                    )
            batch_dicts.append(row_dict)
        pg_conn.execute(insert_sql, batch_dicts)
        total += len(batch)

    return total


def reset_sequences(pg_conn):
    """重置所有 SERIAL 列的序列值为当前最大 ID + 1。"""
    for table_name, col_name in SERIAL_COLUMNS.items():
        try:
            result = pg_conn.execute(
                text(f'SELECT MAX("{col_name}") FROM "{table_name}"')
            )
            max_val = result.scalar()
            if max_val is not None:
                pg_conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}', '{col_name}'), :val)"
                ), {"val": max_val})
                print(f"  Sequence {table_name}.{col_name} → {max_val}")
        except Exception as e:
            # 表可能为空或没有序列
            print(f"  Skip sequence {table_name}.{col_name}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument(
        "--sqlite-path", default="./news_agent.db",
        help="Path to SQLite database file (default: ./news_agent.db)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Batch size for inserts (default: 500)"
    )
    args = parser.parse_args()

    # PostgreSQL URL 从环境变量获取
    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url or not (pg_url.startswith("postgresql") or pg_url.startswith("postgres")):
        print("ERROR: DATABASE_URL must be a PostgreSQL URL")
        print("Example: DATABASE_URL=postgresql://xwatcher:changeme@localhost:5432/xwatcher")
        sys.exit(1)

    sqlite_url = f"sqlite:///{args.sqlite_path}"

    print(f"Source: {sqlite_url}")
    print(f"Target: {pg_url}")
    print(f"Batch size: {args.batch_size}")
    print()

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)

    with sqlite_engine.connect() as sqlite_conn, pg_engine.connect() as pg_conn:
        # 获取 PostgreSQL 中存在的表
        pg_tables = set(inspect(pg_conn).get_table_names())

        print("=" * 60)
        print("Starting migration...")
        print("=" * 60)

        total_rows = 0
        for table_name in MIGRATION_ORDER:
            if table_name in SKIP_TABLES:
                print(f"  SKIP {table_name} (in skip list)")
                continue
            if table_name not in pg_tables:
                print(f"  SKIP {table_name} (not in PostgreSQL)")
                continue

            try:
                count = migrate_table(sqlite_conn, pg_conn, table_name, args.batch_size)
                total_rows += count
                status = f"{count} rows" if count > 0 else "empty"
                print(f"  OK   {table_name}: {status}")
            except Exception as e:
                print(f"  FAIL {table_name}: {e}")
                pg_conn.rollback()
                raise

        print()
        print("Resetting sequences...")
        reset_sequences(pg_conn)

        pg_conn.commit()

        print()
        print("=" * 60)
        print(f"Migration complete! Total rows: {total_rows}")
        print("=" * 60)


if __name__ == "__main__":
    main()
