"""/compact — 影响界面命令（F9）。"""

from __future__ import annotations

from mewcode.cmd.uictl import UICtl


def cmd_compact(args: str, ui: UICtl) -> None:
    """手动触发上下文压缩。"""
    ui.trigger_compact()
