"""/permission — 纯本地命令（F15）。"""

from __future__ import annotations

from mewcode.cmd.uictl import UICtl


def cmd_permission(args: str, ui: UICtl) -> None:
    """显示当前权限模式字符串（与 /status 中相同形式）。"""
    ui.show_info(f"当前权限模式: {ui.get_permission_mode()}")
