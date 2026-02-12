"""调度器访问模块。

提供从 Service 层安全访问 APScheduler 实例的接口，避免循环导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None


def register_scheduler(scheduler: BackgroundScheduler) -> None:
    """注册调度器引用。在 main.py lifespan 启动时调用。"""
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> BackgroundScheduler | None:
    """获取调度器引用。返回 None 表示调度器未运行。"""
    return _scheduler


def unregister_scheduler() -> None:
    """注销调度器引用。在 main.py lifespan 关闭时调用。"""
    global _scheduler
    _scheduler = None
