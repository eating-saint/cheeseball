"""/memory — 纯本地命令（F14）。"""

from __future__ import annotations

from cheeseball.cmd.uictl import UICtl


def cmd_memory(args: str, ui: UICtl) -> None:
    """列出已加载的记忆文件名（仅文件名，不展开内容）。"""
    names = ui.get_memory_file_names()
    if not names:
        ui.show_info("无已加载的记忆条目")
        return
    lines = ["已加载的记忆条目:"]
    for name in names:
        lines.append(f"  - {name}")
    ui.show_info("\n".join(lines))
