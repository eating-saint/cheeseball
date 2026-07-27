"""第 6 章：Agent 权限系统。

五层递进防御：黑名单 → 路径沙箱 → 规则引擎 → 权限模式 → 人在回路。
"""

from mewcode.permission.blacklist import Blacklist
from mewcode.permission.engine import PermissionEngine
from mewcode.permission.modes import (
    MODE_FALLBACK,
    Mode,
    ToolCategory,
    categorize,
    cycle_mode,
    get_fallback,
)
from mewcode.permission.rules import RuleEngine
from mewcode.permission.sandbox import PathSandbox
from mewcode.permission.types import CheckResult, Rule, Verdict

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
