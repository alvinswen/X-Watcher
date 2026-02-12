"""scheduler_accessor 单元测试。

测试调度器引用的注册、获取、注销生命周期。
"""

from unittest.mock import MagicMock

from src.scheduler_accessor import get_scheduler, register_scheduler, unregister_scheduler


class TestSchedulerAccessor:
    """测试调度器访问模块。"""

    def setup_method(self):
        """每个测试前清理状态。"""
        unregister_scheduler()

    def teardown_method(self):
        """每个测试后清理状态。"""
        unregister_scheduler()

    def test_get_scheduler_returns_none_when_not_registered(self):
        """未注册时获取调度器应返回 None。"""
        assert get_scheduler() is None

    def test_register_and_get_scheduler(self):
        """注册后应能获取到调度器实例。"""
        mock_scheduler = MagicMock()
        register_scheduler(mock_scheduler)
        assert get_scheduler() is mock_scheduler

    def test_unregister_scheduler(self):
        """注销后获取调度器应返回 None。"""
        mock_scheduler = MagicMock()
        register_scheduler(mock_scheduler)
        assert get_scheduler() is not None

        unregister_scheduler()
        assert get_scheduler() is None

    def test_full_lifecycle(self):
        """完整生命周期：未注册→注册→获取→注销→再获取返回 None。"""
        # 未注册
        assert get_scheduler() is None

        # 注册
        mock_scheduler = MagicMock()
        register_scheduler(mock_scheduler)

        # 获取
        assert get_scheduler() is mock_scheduler

        # 注销
        unregister_scheduler()

        # 再获取
        assert get_scheduler() is None
