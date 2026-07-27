"""内置命令 handler 包。

每个 handler 签名：(args: str, ui: UICtl) -> None
"""

from __future__ import annotations

from mewcode.cmd.handlers.help import cmd_help, set_registry
from mewcode.cmd.handlers.status import cmd_status
from mewcode.cmd.handlers.memory import cmd_memory
from mewcode.cmd.handlers.permission import cmd_permission
from mewcode.cmd.handlers.session import cmd_session
from mewcode.cmd.handlers.exit import cmd_exit
from mewcode.cmd.handlers.plan import cmd_plan
from mewcode.cmd.handlers.do import cmd_do
from mewcode.cmd.handlers.compact import cmd_compact
from mewcode.cmd.handlers.resume import cmd_resume
from mewcode.cmd.handlers.clear import cmd_clear
from mewcode.cmd.handlers.review import cmd_review

__all__ = [
    "cmd_help",
    "cmd_status",
    "cmd_memory",
    "cmd_permission",
    "cmd_session",
    "cmd_exit",
    "cmd_plan",
    "cmd_do",
    "cmd_compact",
    "cmd_resume",
    "cmd_clear",
    "cmd_review",
    "set_registry",
]
