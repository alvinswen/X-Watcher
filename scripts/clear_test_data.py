#!/usr/bin/env python
"""清除测试数据脚本。

清除数据库中因测试产生的数据，保留管理员用户。
清除顺序遵循外键依赖关系。
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.models import get_engine


def clear_test_data() -> None:
    """清除所有测试数据，保留 users 表。

    清除顺序：
    1. summaries（依赖 tweets）
    2. deduplication_groups（依赖 tweets）
    3. tweets
    4. twitter_follows（依赖 users）
    5. scraper_follows（独立表）
    """
    engine = get_engine()

    tables_to_clear = [
        "summaries",
        "deduplication_groups",
        "tweets",
        "twitter_follows",
        "scraper_follows",
    ]

    with Session(engine) as session:
        print("=" * 50)
        print("开始清除测试数据（保留 users 表）")
        print("=" * 50)

        for table_name in tables_to_clear:
            # 先统计当前记录数
            try:
                count_result = session.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                )
                count = count_result.scalar()
            except Exception:
                print(f"  [{table_name}] 表不存在，跳过")
                continue

            # 执行删除
            session.execute(text(f"DELETE FROM {table_name}"))
            print(f"  [{table_name}] 已清除 {count} 条记录")

        session.commit()
        print("=" * 50)
        print("测试数据清除完成！")

        # 验证 users 表保留情况
        user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        print(f"  [users] 保留 {user_count} 条记录")
        print("=" * 50)


if __name__ == "__main__":
    clear_test_data()
