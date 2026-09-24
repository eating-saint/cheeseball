"""权限系统共享数据类型。

Verdict — 五层判定后的结论
Rule — 一条权限规则
CheckResult — 单次权限检查的返回
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    """五层判定后返回的结论。"""

    ALLOW = "allow"   # 放行，交给 executor
    DENY = "deny"     # 拒绝，构造 ToolResult(success=False)
    ASK = "ask"       # 需要用户确认，由 Agent 层处理


@dataclass
class Rule:
    """一条权限规则，格式为"工具名(模式)"。

    Attributes:
        tool: 工具名, e.g. "Bash", "WriteFile"
        pattern: 匹配模式, e.g. "git *", "*.md"
        result: "allow" | "deny"
        source: 规则来源 "session" | "local" | "project" | "user"
    """

    tool: str
    pattern: str
    result: str
    source: str


@dataclass
class CheckResult:
    """单次权限检查的返回。

    Attributes:
        verdict: ALLOW / DENY / ASK
        reason: 可读原因, e.g. "BLACKLIST: rm -rf /"
    """

    verdict: Verdict
    reason: str
