import asyncio

from src.data_layer.bench.harness import Side, Timing, _stats, measure_side


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
