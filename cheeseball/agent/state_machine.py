"""Agent 循环状态机：显式状态枚举 + 转移逻辑 + 停止条件判断。"""

from __future__ import annotations

from enum import Enum, auto

from cheeseball.agent.events import StopReason


class AgentState(Enum):
    """Agent 循环的四个状态。"""
    IDLE = auto()       # 等待用户输入
    THINKING = auto()   # LLM 流式响应进行中
    EXECUTING = auto()  # 工具执行中
    DONE = auto()       # 循环正常/异常终止


class LoopStateMachine:
    """管理 Agent 循环的状态转移和停止条件判断。

    用法::

        sm = LoopStateMachine(max_iterations=35)
        state, reason = sm.start_round()       # IDLE → THINKING
        state = sm.on_stream_done(True)        # THINKING → EXECUTING
        state, reason = sm.on_tools_executed(0, 3)  # EXECUTING → THINKING
    """

    def __init__(self, max_iterations: int = 35) -> None:
        self._state = AgentState.IDLE
        self._iteration = 0
        self._max_iterations = max_iterations
        self._consecutive_unknown = 0

    # ── 只读属性 ──────────────────────────────────────────────

    @property
    def state(self) -> AgentState:
        """当前状态。"""
        return self._state

    @property
    def iteration(self) -> int:
        """当前迭代轮次（从 1 开始）。"""
        return self._iteration

    @property
    def max_iterations(self) -> int:
        """最大迭代轮次上限。"""
        return self._max_iterations

    @property
    def consecutive_unknown(self) -> int:
        """连续未知工具计数。"""
        return self._consecutive_unknown

    # ── 状态转移 ──────────────────────────────────────────────

    def start_round(self) -> tuple[AgentState, StopReason | None]:
        """开始新一轮：IDLE/EXECUTING → THINKING，迭代计数+1。

        Returns:
            (new_state, stop_reason_or_none)
            若超过迭代上限，返回 (DONE, ITERATION_LIMIT)。
        """
        self._iteration += 1
        if self._iteration > self._max_iterations:
            self._state = AgentState.DONE
            return (self._state, StopReason.ITERATION_LIMIT)

        self._state = AgentState.THINKING
        return (self._state, None)

    def on_stream_done(self, has_tool_calls: bool) -> AgentState:
        """LLM 流结束后转移。

        Args:
            has_tool_calls: True 表示本轮产出了工具调用。

        Returns:
            EXECUTING（有工具调用）或 DONE（无工具，自然完成）。
        """
        if has_tool_calls:
            self._state = AgentState.EXECUTING
        else:
            self._state = AgentState.DONE
        return self._state

    def on_tools_executed(
        self, unknown_count: int, total_count: int
    ) -> tuple[AgentState, StopReason | None]:
        """工具执行完毕后转移。

        Args:
            unknown_count: 本轮中未注册的工具数量。
            total_count: 本轮总工具调用数量。

        Returns:
            (new_state, stop_reason_or_none)
            全部未知 → 连续计数+1，≥3 则 (DONE, CONSECUTIVE_UNKNOWN)。
            有合法工具 → 重置计数 → THINKING。
        """
        if total_count > 0 and unknown_count == total_count:
            self._consecutive_unknown += 1
            if self._consecutive_unknown >= 3:
                self._state = AgentState.DONE
                return (self._state, StopReason.CONSECUTIVE_UNKNOWN)
        else:
            self._consecutive_unknown = 0

        self._state = AgentState.THINKING
        return (self._state, None)

    def on_stream_error(self) -> tuple[AgentState, StopReason]:
        """流式响应出错 → DONE (STREAM_ERROR)。"""
        self._state = AgentState.DONE
        return (self._state, StopReason.STREAM_ERROR)

    def on_cancel(self) -> tuple[AgentState, StopReason]:
        """用户取消 → DONE (USER_CANCEL)。"""
        self._state = AgentState.DONE
        return (self._state, StopReason.USER_CANCEL)
