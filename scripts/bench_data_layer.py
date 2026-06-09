"""M-5 子项目 6:file vs sqlalchemy 数据层性能基准。

用法(旧 app venv,pg 容器需起 + data_migrated 需迁好):
  XWATCHER_DATA_ROOT=./data_migrated .venv/bin/python scripts/bench_data_layer.py [--n-warm 7] [--author <name>] [--batch 100]
单进程交替切 env;cold(首调)+warm 中位;正确性预检每条调用计数;出 stdout 表 + bench_results.json;
任一阶段失败 → exit 1(独立取退码,不靠管道 $?)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data_layer.bench import cases as C  # noqa: E402
from src.data_layer.bench.harness import PathResult, measure_side, render_report  # noqa: E402


async def _preflight(data_root: str) -> None:
    """环境预检:data_migrated 存在 + file 全量读计数 + DB 全量读计数(sync export 路径首次对 pg 实跑)。"""
    if not Path(data_root).exists():
        print(f"[PREFLIGHT FAIL] data_root 不存在: {data_root}", file=sys.stderr)
        raise SystemExit(1)

    with C.data_layer_mode("file", data_root=data_root):
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        n_file = len(await FileTweetStore(Path(data_root)).get_all_tweets())
    print(f"[PREFLIGHT] file get_all_tweets = {n_file}")

    repo, session = C._sync_export_repo()
    try:
        n_db = len(repo.get_tweets(since=None, until=None, authors=None))
    finally:
        session.close()
    print(f"[PREFLIGHT] db export.get_tweets = {n_db}")

    if n_file == 0 or n_db == 0:
        print("[PREFLIGHT FAIL] 计数为 0,数据底座未就绪", file=sys.stderr)
        raise SystemExit(1)
    if n_file != n_db:
        print(f"[PREFLIGHT WARN] file({n_file}) != db({n_db}) 计数不一致(报告须标注)", file=sys.stderr)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-warm", type=int, default=7)
    ap.add_argument("--author", default=None, help="索引读/分页用作者名(默认探测真实高频作者)")
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--data-root", default=os.environ.get("XWATCHER_DATA_ROOT", "./data_migrated"))
    args = ap.parse_args()
    data_root = args.data_root

    await _preflight(data_root)

    author = args.author or C.probe_real_author(data_root)
    print(f"[RUN] author={author} n_warm={args.n_warm} batch={args.batch}")

    results: list[PathResult] = []

    bench_cases = (
        C.build_read_cases(data_root=data_root, author=author)
        + [C.build_write_case(data_root=data_root, batch_size=args.batch)]
        + [C.build_aggregate_case(data_root=data_root)]
        + [C.build_handle_acquisition_case(data_root=data_root)]
    )

    for case in bench_cases:
        with C.data_layer_mode("file", data_root=data_root):
            file_t = await measure_side(case.file, n_warm=args.n_warm)
        db_t = None
        if case.db is not None:
            with C.data_layer_mode("sqlalchemy"):
                db_t = await measure_side(case.db, n_warm=args.n_warm)
        results.append(PathResult(name=case.name, file=file_t, db=db_t, note=case.note))
        print(f"[OK] {case.name}: file warm={file_t.warm_median_s:.4f}s"
              + (f" db warm={db_t.warm_median_s:.4f}s" if db_t else " (file-only)"))

    copytree_s, copytree_mb = C.build_copytree_probe(data_root=data_root)()
    bridge_ms = await C.measure_bridge_overhead_ms(n=args.n_warm)
    nit3_ms = await C.measure_nit3_engine_ms(n=args.n_warm)
    extras = {
        "bridge_overhead_ms": round(bridge_ms, 3),
        "copytree_s": round(copytree_s, 3),
        "copytree_mb": round(copytree_mb, 1),
        "nit3_engine_ms": round(nit3_ms, 3),
    }
    print(f"[EXTRAS] {extras}")

    md = render_report(results, extras=extras)
    print("\n" + md)

    out = {"results": [{"name": r.name, "file": asdict(r.file),
                        "db": (asdict(r.db) if r.db else None), "note": r.note} for r in results],
           "extras": extras, "author": author}
    Path(REPO / "bench_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print("[DONE] wrote bench_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
