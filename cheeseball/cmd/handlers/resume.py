"""/resume — 影响界面命令（F10）。"""

from __future__ import annotations

from cheeseball.cmd.uictl import UICtl


def cmd_resume(args: str, ui: UICtl) -> None:
    """打开历史会话列表，选中后从该会话最后一个 compact 标记之后恢复。"""
    ui.open_session_list()
