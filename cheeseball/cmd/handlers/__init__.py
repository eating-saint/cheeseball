"""内置命令 handler 包。

每个 handler 签名：(args: str, ui: UICtl) -> None
"""

from __future__ import annotations

from cheeseball.cmd.handlers.help import cmd_help, set_registry
from cheeseball.cmd.handlers.status import cmd_status
from cheeseball.cmd.handlers.memory import cmd_memory
from cheeseball.cmd.handlers.permission import cmd_permission
from cheeseball.cmd.handlers.session import cmd_session
from cheeseball.cmd.handlers.exit import cmd_exit
from cheeseball.cmd.handlers.plan import cmd_plan
from cheeseball.cmd.handlers.do import cmd_do
from cheeseball.cmd.handlers.compact import cmd_compact
from cheeseball.cmd.handlers.resume import cmd_resume
from cheeseball.cmd.handlers.clear import cmd_clear
from cheeseball.cmd.handlers.review import cmd_review

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
