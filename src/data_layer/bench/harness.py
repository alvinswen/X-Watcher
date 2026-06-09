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
