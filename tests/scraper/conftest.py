"""tests/scraper 公共 fixture（CHG-039 · R9a 测试地基）。

两个 autouse fixture 覆盖本目录全部测试；二者零共享状态（前者只碰
src.scraper.client._circuit_breaker 实例字段，后者只碰 TaskRegistry 类属性），
执行序可交换，无隐式定义序依赖。
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_circuit_breaker():
    """隔离 src/scraper/client.py:351 的进程级熔断器单例（所有 TwitterClient 共享）。

    根因：失败计数跨测试累积，选择性执行/跨目录收集序下 ≥5 个计数失败测试
    连续即 OPEN（60s monotonic 冷却 > 剩余套件时长），后续真实 fetch 链测试全崩。
    就地还原三字段（不重建实例——重建会与 get_twitter_circuit_breaker() 及
    client 内引用脱钩），范式对齐 tests/mcp/conftest.py 的 _isolate_mcp_transport。
    """
    import src.scraper.client as client_module

    cb = client_module._circuit_breaker
    prev = (cb._state, cb._failure_count, cb._last_failure_time)
    yield
    cb._state, cb._failure_count, cb._last_failure_time = prev


@pytest.fixture(autouse=True)
def clean_registry():
    """TaskRegistry 单例保存 + 注册表清空 + 身份还原（单链固定序 · autouse 覆盖全目录）。

    固定序：保存类属性 → get_instance()（单例为空时创建）+ clear_all() → yield
    → 清空当前实例 → 还原类属性。保存必然先于 get_instance() 的"空时顺手创建
    实例"副作用（task_registry.py:86-92），还原值不可能被新建实例覆盖。
    teardown 重读当前 TaskRegistry._instance（不用 setup 捕获引用），对
    setup_method 砸点（test_task_registry.py:24-25 等 5 对）次序鲁棒。
    名字保留 clean_registry：tests/scraper 3 文件 33 处形参引用零改动解析到本定义。
    """
    from src.scraper.task_registry import TaskRegistry

    prev_instance = TaskRegistry._instance
    prev_initialized = TaskRegistry._initialized
    TaskRegistry.get_instance().clear_all()
    yield
    current = TaskRegistry._instance
    if current is not None:
        current.clear_all()
    TaskRegistry._instance = prev_instance
    TaskRegistry._initialized = prev_initialized
