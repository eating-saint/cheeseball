"""/session — 纯本地命令（F16）。"""

from __future__ import annotations

from mewcode.cmd.uictl import UICtl


def cmd_session(args: str, ui: UICtl) -> None:
    """显示当前会话标识信息：存档路径 + session ID。"""
    lines = [
        f"会话 ID  : {ui.get_session_id()}",
        f"存档路径  : {ui.get_archive_path()}",
    ]
    ui.show_info("\n".join(lines))
