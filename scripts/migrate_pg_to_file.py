"""M-5 子项目 1:PostgreSQL → 文件层 存量迁移 + 校验。

用法(旧 app venv,pg 容器需起):
  XWATCHER_DATA_ROOT=<p> .venv/bin/python scripts/migrate_pg_to_file.py [--only <entity>] [--data-root <p>]
读真 pg(复用 src.database.async_session 的 DATABASE_URL)、按单元迁移+校验、出报告;任一单元 FAIL → exit 1。
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 迁移单元注册:entity -> async migrator(session, data_root) -> MigrationReport
# 各 migrator 在后续 Task 注册进此 dict。
from src.data_layer.migration import registry  # noqa: E402

# migrator 模块 import(import 即注册进 registry.MIGRATORS),随各 Task 增量加入:
from src.data_layer.migration import schedule  # noqa: E402,F401
from src.data_layer.migration import follows  # noqa: E402,F401


async def _run(only: str | None, data_root: Path):
    from src.database.async_session import get_async_session_maker
    session_maker = get_async_session_maker()
    reports = []
    entities = [only] if only else list(registry.MIGRATORS.keys())
    async with session_maker() as session:
        for ent in entities:
            migrator = registry.MIGRATORS[ent]
            rep = await migrator(session, data_root)
            print(rep.line())
            reports.append(rep)
    return reports


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--data-root", default=os.environ.get("XWATCHER_DATA_ROOT", "data"))
    args = ap.parse_args()
    data_root = Path(args.data_root)
    reports = asyncio.run(_run(args.only, data_root))
    failed = [r for r in reports if not r.ok]
    print(f"\n=== {len(reports)-len(failed)}/{len(reports)} OK ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
