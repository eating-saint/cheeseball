"""第 6 章：Agent 权限系统。

五层递进防御：黑名单 → 路径沙箱 → 规则引擎 → 权限模式 → 人在回路。
"""

from cheeseball.permission.blacklist import Blacklist
from cheeseball.permission.engine import PermissionEngine
from cheeseball.permission.modes import (
    MODE_FALLBACK,
    Mode,
    ToolCategory,
    categorize,
    cycle_mode,
    get_fallback,
)
from cheeseball.permission.rules import RuleEngine
from cheeseball.permission.sandbox import PathSandbox
from cheeseball.permission.types import CheckResult, Rule, Verdict

__all__ = [
    "Blacklist",
    "CheckResult",
    "Mode",
    "MODE_FALLBACK",
    "PathSandbox",
    "PermissionEngine",
    "Rule",
    "RuleEngine",
    "ToolCategory",
    "Verdict",
    "categorize",
    "cycle_mode",
    "get_fallback",
]
