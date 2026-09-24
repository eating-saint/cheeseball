"""Agent 事件系统数据类型，替换 ch03 的 Event/ToolEvent/Phase。

Agent 对外通过 AgentEvent 与 UI 通信，UI 按非 None 字段分派渲染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cheeseball.provider import ToolCall


class StopReason(Enum):
    """循环停止原因。"""
    NATURAL = "natural"
    ITERATION_LIMIT = "iteration_limit"
    USER_CANCEL = "user_cancel"
    CONSECUTIVE_UNKNOWN = "consecutive_unknown"
    STREAM_ERROR = "stream_error"


@dataclass
class TokenUsage:
    """一轮 LLM 请求的 token 用量。"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class IterationProgress:
    """迭代进度，每轮开始前产出。"""
    current: int
    max: int


@dataclass
class ToolStart:
    """工具调用开始事件。"""
    tool_id: str
    tool_name: str
    args_preview: str


@dataclass
class ToolEnd:
    """工具调用结束事件，含结果摘要。"""
    tool_id: str
    tool_name: str
    result_summary: str
    is_error: bool = False


@dataclass
class DoneInfo:
    """循环终止信息。"""
    reason: StopReason
    message: str = ""


@dataclass
class AgentEvent:
    """Agent 对外统一事件载体。

    TUI 消费时按非 None / 非默认值字段分派渲染：
    - text: 追加到当前 AI 回复文本
    - tool_start: 动态区新增工具行
    - tool_end: 弹出对应工具行，落 RichLog
    - token_usage: 累加状态栏用量
    - iteration: 更新轮次显示
    - done: 本轮结束
    - error: 错误提示
    """

    text: str = ""
    tool_start: ToolStart | None = None
    tool_end: ToolEnd | None = None
    token_usage: TokenUsage | None = None
    iteration: IterationProgress | None = None
    done: DoneInfo | None = None
    error: str = ""
    permission_request: PermissionRequest | None = None


# ── 权限系统事件 ──────────────────────────────────────────────────


class PermissionChoice(Enum):
    """人在回路：用户对权限确认的三种选择。"""

    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY_ONCE = "deny_once"


@dataclass
class PermissionRequest:
    """Agent 向 TUI 发出的权限确认请求。

    Attributes:
        tool_name: 工具名, e.g. "Bash"
        args_preview: 参数预览, e.g. "git status"
        reason: 需要确认的原因, e.g. "default 模式下命令执行需确认"
    """

    tool_name: str
    args_preview: str
    reason: str


@dataclass
class PermissionResponse:
    """TUI 回传给 Agent 的用户选择。

    Attributes:
        tool_name: 工具名（回传用于匹配）
        choice: 用户选择
    """

    tool_name: str
    choice: PermissionChoice


@dataclass
class CollectedRound:
    """一轮 LLM 响应的完整收集结果，供循环判断下一步。"""
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
