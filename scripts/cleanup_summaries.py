#!/usr/bin/env python
"""清理摘要记录脚本。

删除 summaries 表中的记录，以便使用新的 prompt 重新生成。
支持两种模式：
  --all     删除所有摘要记录（默认）
  --failed  仅删除翻译为空的失败记录
"""

import argparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.models import get_engine


def cleanup_summaries(failed_only: bool = False) -> None:
    """清理摘要记录。

    Args:
        failed_only: 如果为 True，仅删除 translation_text 为空的失败记录
    """
    engine = get_engine()

    with Session(engine) as session:
        print("=" * 50)

        # 统计当前记录数
        try:
            total_count = session.execute(
                text("SELECT COUNT(*) FROM summaries")
            ).scalar()
        except Exception:
            print("summaries 表不存在，无需清理")
            return

        if failed_only:
            print(f"清理失败的摘要记录（translation_text 为空）")
            # 统计失败记录数
            failed_count = session.execute(
                text(
                    "SELECT COUNT(*) FROM summaries "
                    "WHERE translation_text IS NULL AND is_generated_summary = 1"
                )
            ).scalar()
            print(f"  总记录数: {total_count}")
            print(f"  失败记录数: {failed_count}")

            # 删除失败记录
            session.execute(
                text(
                    "DELETE FROM summaries "
                    "WHERE translation_text IS NULL AND is_generated_summary = 1"
                )
            )
            print(f"  已删除 {failed_count} 条失败记录")
        else:
            print(f"清理所有摘要记录")
            print(f"  总记录数: {total_count}")

            # 删除所有记录
            session.execute(text("DELETE FROM summaries"))
            print(f"  已删除 {total_count} 条记录")

        session.commit()

        # 验证
        remaining = session.execute(
            text("SELECT COUNT(*) FROM summaries")
        ).scalar()
        print(f"  剩余记录数: {remaining}")
        print("=" * 50)
        print("清理完成！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理摘要记录")
    parser.add_argument(
        "--failed",
        action="store_true",
        help="仅删除失败的记录（translation_text 为空）",
    )
    args = parser.parse_args()

    cleanup_summaries(failed_only=args.failed)
