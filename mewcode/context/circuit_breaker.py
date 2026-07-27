"""自动摘要熔断器（F28-F29, N2）。

连续失败 CIRCUIT_BREAKER_THRESHOLD 次后熔断，阻止后续自动触发。
线程安全。仅由 ContextManager.compact(trigger="auto") 路径操作。

契约：
- compact(trigger="auto"): 成功 → cb.success()，失败 → cb.failure()
- compact(trigger="manual"/"emergency"): 永远不调 success/failure
- should_auto_compact() 在 tripped=True 时返回 False
"""

from __future__ import annotations

import threading

from mewcode.context.constants import CIRCUIT_BREAKER_THRESHOLD


class CircuitBreaker:
    """自动摘要熔断器。

    用法::

        cb = CircuitBreaker()
        cb.failure()  # 自动摘要失败时调用
        cb.failure()
        cb.failure()
        assert cb.tripped()  # 连续 3 次失败 → 熔断
        cb.success()  # 某次成功后重置
        assert not cb.tripped()
    """

    THRESHOLD: int = CIRCUIT_BREAKER_THRESHOLD

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: int = 0

    def success(self) -> None:
        """重置失败计数到零（自动摘要成功时调用，F28）。"""
        with self._lock:
            self._failures = 0

    def failure(self) -> None:
        """累加一次失败（自动摘要失败时调用，F28）。"""
        with self._lock:
            self._failures += 1

    def tripped(self) -> bool:
        """检查熔断器是否已断开。

        Returns:
            True 如果失败次数达到阈值，应阻止后续自动摘要。
        """
        with self._lock:
            return self._failures >= self.THRESHOLD
