"""轻量级熔断器。

三状态模型：CLOSED → OPEN → HALF_OPEN → CLOSED
防止下游服务不可用时持续发送无效请求。
"""

import logging
import threading
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """线程安全的熔断器。

    Args:
        name: 熔断器名称（用于日志标识）
        failure_threshold: 连续失败次数阈值，达到后触发熔断
        recovery_timeout: 熔断后等待恢复的秒数
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前状态（自动检查是否应从 OPEN 转为 HALF_OPEN）。"""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._last_failure_time >= self.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "熔断器 [%s] 状态变更: OPEN → HALF_OPEN（冷却期已过）",
                    self.name,
                )
            return self._state

    def allow_request(self) -> bool:
        """判断当前是否允许发送请求。

        - CLOSED: 允许
        - OPEN: 拒绝
        - HALF_OPEN: 允许（探测请求）
        """
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        """记录一次成功调用。"""
        with self._lock:
            old_state = self._state
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            if old_state != CircuitState.CLOSED:
                logger.info(
                    "熔断器 [%s] 状态变更: %s → CLOSED（请求成功）",
                    self.name,
                    old_state.value,
                )

    def record_failure(self) -> None:
        """记录一次失败调用。"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # 探测请求失败，重新熔断
                self._state = CircuitState.OPEN
                logger.warning(
                    "熔断器 [%s] 状态变更: HALF_OPEN → OPEN（探测失败）",
                    self.name,
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    "熔断器 [%s] 状态变更: CLOSED → OPEN"
                    "（连续失败 %d 次，冷却 %.0f 秒）",
                    self.name,
                    self._failure_count,
                    self.recovery_timeout,
                )

    def get_status(self) -> dict[str, Any]:
        """获取熔断器状态摘要（用于健康检查/监控）。"""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._last_failure_time >= self.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "熔断器 [%s] 状态变更: OPEN → HALF_OPEN（冷却期已过）",
                    self.name,
                )
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
            }
