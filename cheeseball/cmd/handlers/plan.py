"""/plan — 影响界面命令（F7）。"""

from __future__ import annotations

from cheeseball.cmd.uictl import UICtl


def cmd_plan(args: str, ui: UICtl) -> None:
    """切换运行时权限模式到计划模式。"""
    ui.set_permission_mode("plan")
    ui.show_info("已进入计划模式（Plan Mode）。只读工具可用，请探索并输出执行计划。输入 /do 执行。")
