"""登录失败限流器（CHG-041 · 全实例单闸 · 内存态）。

- 连续失败满 max_failures 次 → 锁定 lockout_seconds；锁定期内一切登录
  请求（含正确密码）均拒；到点自动解锁并清零；登录成功清零；重启清零。
- clock 可注入（默认 time.monotonic）——[E2E-EFFECT] 可控时间源，
  测试经 tests/user/conftest.py autouse fixture 隔离（CHG-039 范式）。
- 无锁设计：uvicorn 单进程单事件循环，check/record 均为无 await 的同步
  方法，无跨线程写点；并发退化最坏为计数少加一次，不影响阈值语义。
"""

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60.0


class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int = MAX_CONSECUTIVE_FAILURES,
        lockout_seconds: float = LOCKOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self.clock = clock
        self._failure_count = 0
        self._locked_until: float | None = None

    def check_locked(self) -> float | None:
        """锁定中返回剩余秒数；未锁定返回 None（到点自动解锁并清零计数）。"""
        if self._locked_until is None:
            return None
        remaining = self._locked_until - self.clock()
        if remaining <= 0:
            self._locked_until = None
            self._failure_count = 0
            return None
        return remaining

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self._max_failures and self._locked_until is None:
            self._locked_until = self.clock() + self._lockout_seconds
            logger.warning(
                "登录连续失败已达 %d 次，全实例锁定登录 %d 秒（重启服务可立即解锁）",
                self._failure_count,
                int(self._lockout_seconds),
            )

    def record_success(self) -> None:
        self._failure_count = 0

    def reset(self) -> None:
        self._failure_count = 0
        self._locked_until = None


login_rate_limiter = LoginRateLimiter()
