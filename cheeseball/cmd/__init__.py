"""命令系统包入口（T7）。

导出全部公开 API：
- 类型：CommandKind, CommandDef, ParseResult
- 注册中心：CommandRegistry
- 解析器：Parser
- 分发器：dispatch
- UI 抽象：UICtl
"""

from __future__ import annotations

from cheeseball.cmd.types import CommandKind, CommandDef, ParseResult
from cheeseball.cmd.registry import CommandRegistry
from cheeseball.cmd.parser import Parser
from cheeseball.cmd.dispatcher import dispatch
from cheeseball.cmd.uictl import UICtl

__all__ = [
    "CommandKind",
    "CommandDef",
    "ParseResult",
    "CommandRegistry",
    "Parser",
    "dispatch",
    "UICtl",
]
