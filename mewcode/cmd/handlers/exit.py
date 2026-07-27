"""/exit — 影响界面命令（F6）。"""

from __future__ import annotations

from mewcode.cmd.uictl import UICtl


def cmd_exit(args: str, ui: UICtl) -> None:
    """关闭 TUI 进程。"""
    ui.exit_app()
