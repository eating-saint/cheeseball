"""/do — 提示词注入命令（F8）。"""

from __future__ import annotations

from mewcode.agent.runner import EXECUTE_DIRECTIVE
from mewcode.cmd.uictl import UICtl


def cmd_do(args: str, ui: UICtl) -> None:
    """切回默认模式并注入执行指令，立即触发回合。"""
    ui.set_permission_mode("default")
    text = args.strip() if args.strip() else EXECUTE_DIRECTIVE
    ui.inject_user_message(text)
