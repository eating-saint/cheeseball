"""第 4 层：权限模式与工具分类。

定义四种权限模式对三类工具的兜底裁决矩阵。
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cheeseball.tool.base import Tool

from cheeseball.permission.types import Verdict


class Mode(Enum):
    """四种权限模式。"""

    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    BYPASS_PERMISSIONS = "bypassPermissions"


class ToolCategory(Enum):
    """工具按能力分为三类。"""

    READONLY = "readonly"       # is_readonly=True
    FILE_WRITE = "file_write"   # is_readonly=False 且参数含 path
    COMMAND = "command"         # is_readonly=False 且参数不含 path


# ── 兜底矩阵 ──────────────────────────────────────────────────────

MODE_FALLBACK: dict[Mode, dict[ToolCategory, Verdict]] = {
    Mode.DEFAULT: {
        ToolCategory.READONLY: Verdict.ALLOW,
        ToolCategory.FILE_WRITE: Verdict.ASK,
        ToolCategory.COMMAND: Verdict.ASK,
    },
    Mode.ACCEPT_EDITS: {
        ToolCategory.READONLY: Verdict.ALLOW,
        ToolCategory.FILE_WRITE: Verdict.ALLOW,
        ToolCategory.COMMAND: Verdict.ASK,
    },
    Mode.PLAN: {
        ToolCategory.READONLY: Verdict.ALLOW,
        ToolCategory.FILE_WRITE: Verdict.ASK,
        ToolCategory.COMMAND: Verdict.ASK,
    },
    Mode.BYPASS_PERMISSIONS: {
        ToolCategory.READONLY: Verdict.ALLOW,
        ToolCategory.FILE_WRITE: Verdict.ALLOW,
        ToolCategory.COMMAND: Verdict.ALLOW,
    },
}


def categorize(tool: "Tool") -> ToolCategory:
    """根据工具属性判断其类别。

    Args:
        tool: 工具实例（cheeseball.tool.base.Tool 子类）。

    Returns:
        ToolCategory: 只读 / 文件写 / 命令执行。
    """
    if tool.is_readonly:
        return ToolCategory.READONLY

    # 检查 parameters JSON Schema 的 properties 是否含 "path" 键
    params = tool.parameters
    props = params.get("properties", {})
    if "path" in props:
        return ToolCategory.FILE_WRITE

    return ToolCategory.COMMAND


def get_fallback(mode: Mode, category: ToolCategory) -> Verdict:
    """查询指定模式对指定工具类别的兜底裁决。

    Args:
        mode: 当前权限模式。
        category: 工具类别。

    Returns:
        兜底 Verdict（ALLOW / ASK / DENY）。
    """
    return MODE_FALLBACK[mode][category]


# ── 模式循环顺序 ──────────────────────────────────────────────────

_MODE_ORDER = (Mode.DEFAULT, Mode.ACCEPT_EDITS, Mode.PLAN, Mode.BYPASS_PERMISSIONS)


def cycle_mode(current: Mode, direction: int) -> Mode:
    """循环切换权限模式。

    Args:
        current: 当前模式。
        direction: +1 下一档, -1 上一档。

    Returns:
        切换后的新模式。
    """
    idx = _MODE_ORDER.index(current)
    new_idx = (idx + direction) % len(_MODE_ORDER)
    return _MODE_ORDER[new_idx]
