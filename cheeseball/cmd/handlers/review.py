"""/review — 提示词注入命令（F17）。"""

from __future__ import annotations

from cheeseball.cmd.uictl import UICtl

_REVIEW_TEXT = (
    "请审查当前对话上下文中的代码，给出结构化代码审查意见。"
    "关注：正确性、安全性、性能、可维护性。"
)


def cmd_review(args: str, ui: UICtl) -> None:
    """向对话注入固定文本的代码审查请求，并立即触发回合。"""
    ui.inject_user_message(_REVIEW_TEXT)
