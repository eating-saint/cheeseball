"""/clear — 影响界面命令（F11）。"""

from __future__ import annotations

from cheeseball.cmd.uictl import UICtl


def cmd_clear(args: str, ui: UICtl) -> None:
    """清空对话历史：关闭旧存档 → 新存档 → 清空消息 → token 归零。"""
    ui.clear_conversation()
    ui.show_info("已结束当前会话并开启新会话。旧会话可通过 /resume 恢复。")
