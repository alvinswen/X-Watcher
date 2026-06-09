"""子项目 6 性能基准:纯测量原语(无 DB/IO 依赖,可纯单测)。"""
from __future__ import annotations

import inspect
import statistics
from dataclasses import dataclass
from time import perf_counter
from typing import Callable


@dataclass
class Side:
    """一个被测侧(file 或 db):0-arg thunk + 可选每轮 untimed setup/teardown。"""
    thunk: Callable[[], object]
    setup: Callable[[], object] | None = None
    teardown: Callable[[], object] | None = None


@dataclass
class Timing:
    cold_s: float
    warm_median_s: float
    warm_min_s: float
    warm_max_s: float
    n_warm: int


def _stats(samples: list[float]) -> tuple[float, float, float]:
    """返回 (median, min, max)。"""
    return statistics.median(samples), min(samples), max(samples)


async def _maybe(fn: Callable[[], object] | None) -> None:
    if fn is None:
        return
    r = fn()
    if inspect.isawaitable(r):
        await r


async def measure_side(side: Side, n_warm: int = 7) -> Timing:
    """测 side:cold(首调)+ warm×n_warm 中位/min/max。setup/teardown 每轮调用、不计入计时。"""
    async def _one() -> float:
        await _maybe(side.setup)
        t0 = perf_counter()
        r = side.thunk()
        if inspect.isawaitable(r):
            await r
        dt = perf_counter() - t0
        await _maybe(side.teardown)
        return dt

    cold = await _one()
    warm = [await _one() for _ in range(n_warm)]
    med, lo, hi = _stats(warm)
    return Timing(cold_s=cold, warm_median_s=med, warm_min_s=lo, warm_max_s=hi, n_warm=n_warm)


@dataclass
class PathResult:
    name: str
    file: Timing
    db: Timing | None  # None = file-only(无 DB 配对)
    note: str = ""


def _ratio(file_s: float, db_s: float) -> str:
    if db_s <= 0:
        return "N/A"
    return f"{file_s / db_s:.2f}"


def render_report(results: list[PathResult], *, extras: dict) -> str:
    """渲染 markdown:路径×{file/db cold/warm、warm 倍率} 表 + extras + 缓存边界标注。"""
    lines: list[str] = []
    lines.append("| 路径 | file cold(s) | file warm 中位(s) | db cold(s) | db warm 中位(s) | warm 倍率(file/db) | 备注 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        if r.db is None:
            lines.append(
                f"| {r.name} | {r.file.cold_s:.4f} | {r.file.warm_median_s:.4f} | "
                f"— | — | N/A | {r.note} |"
            )
        else:
            ratio = _ratio(r.file.warm_median_s, r.db.warm_median_s)
            lines.append(
                f"| {r.name} | {r.file.cold_s:.4f} | {r.file.warm_median_s:.4f} | "
                f"{r.db.cold_s:.4f} | {r.db.warm_median_s:.4f} | {ratio} | {r.note} |"
            )
    lines.append("")
    lines.append("**口径/边界(诚实标注):**")
    lines.append("- cold = 进程内首调;**warm-OS-cache 稳态**(OS page cache 未真清,非真冷盘)。")
    if "bridge_overhead_ms" in extras:
        lines.append(f"- asyncio.run 桥基线(loop 起停):约 {extras['bridge_overhead_ms']} ms/次"
                     "(file 模式 export/import 门面每方法调用付一次,不含在上表数据层数字内)。")
    if "copytree_s" in extras:
        lines.append(f"- dry_run copytree(NIT-2):约 {extras['copytree_s']} s / 体积 {extras.get('copytree_mb')} MB"
                     "(一次 import_data 拷 N 份;优化项=只拷 category 涉及子目录,留 future)。")
    if "nit3_engine_ms" in extras:
        lines.append(f"- NIT-3:file 模式 export/import 路径仍建 sync engine+Session 约 {extras['nit3_engine_ms']} ms"
                     "(建连开销,适配器忽略 session)。")
    return "\n".join(lines)
