import asyncio

from src.data_layer.bench.harness import (
    PathResult,
    Side,
    Timing,
    _stats,
    measure_side,
    render_report,
)


def test_stats_median_min_max():
    assert _stats([0.3, 0.1, 0.2]) == (0.2, 0.1, 0.3)


async def test_measure_side_async_thunk_cold_plus_warm():
    calls = {"n": 0}

    async def thunk():
        calls["n"] += 1
        await asyncio.sleep(0.005)

    t = await measure_side(Side(thunk=thunk), n_warm=3)
    assert isinstance(t, Timing)
    assert t.n_warm == 3
    assert calls["n"] == 4  # 1 cold + 3 warm
    assert t.cold_s > 0 and t.warm_median_s > 0
    assert t.warm_min_s <= t.warm_median_s <= t.warm_max_s


async def test_measure_side_sync_thunk_supported():
    def thunk():
        return sum(range(1000))

    t = await measure_side(Side(thunk=thunk), n_warm=2)
    assert t.n_warm == 2 and t.warm_median_s >= 0


async def test_measure_side_setup_teardown_untimed_each_run():
    order = []

    async def setup():
        order.append("setup")

    async def teardown():
        order.append("teardown")

    async def thunk():
        order.append("call")

    await measure_side(Side(thunk=thunk, setup=setup, teardown=teardown), n_warm=1)
    # 1 cold + 1 warm = 2 轮,每轮 setup→call→teardown
    assert order == ["setup", "call", "teardown", "setup", "call", "teardown"]


def _t(cold, warm):
    return Timing(cold_s=cold, warm_median_s=warm, warm_min_s=warm, warm_max_s=warm, n_warm=7)


def test_render_report_paired_path_has_ratio():
    results = [PathResult(name="全量读", file=_t(2.0, 1.0), db=_t(0.4, 0.2), note="")]
    md = render_report(results, extras={})
    assert "全量读" in md
    assert "5.0" in md or "5.00" in md  # warm 倍率 file/db = 1.0/0.2 = 5.0


def test_render_report_file_only_path_no_ratio():
    results = [PathResult(name="by-day", file=_t(0.1, 0.05), db=None, note="无 DB repo 配对")]
    md = render_report(results, extras={})
    assert "by-day" in md
    assert "无 DB repo 配对" in md
    assert "N/A" in md  # file-only 路径倍率列 N/A


def test_render_report_includes_extras_and_cache_caveat():
    md = render_report([], extras={"bridge_overhead_ms": 1.23, "copytree_s": 4.5,
                                   "copytree_mb": 42.0, "nit3_engine_ms": 0.8})
    assert "1.23" in md and "4.5" in md and "42.0" in md and "0.8" in md
    assert "warm-OS" in md  # 诚实缓存边界标注
