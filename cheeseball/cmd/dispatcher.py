"""命令分发器（F3, N3a）。

根据 CommandKind + 运行时状态分发执行。
"""

from __future__ import annotations

from cheeseball.cmd.types import CommandDef, CommandKind
from cheeseball.cmd.uictl import UICtl


def dispatch(cmd: CommandDef, args: str, ui: UICtl) -> None:
    """按命令类型和运行时状态分发。

    - LOCAL: 不检查 idle，同步调用 handler
    - UI: 检查 idle，非 idle 拒绝并提示
    - PROMPT: 检查 idle，非 idle 拒绝并提示

    Args:
        cmd: 命中的命令定义。
        args: 参数字符串。
        ui: UI 控制接口。
    """
    if cmd.kind == CommandKind.LOCAL:
        # 纯本地命令：任何状态均可执行
        cmd.handler(args, ui)
        return

    # UI 和 PROMPT 命令：需 idle 状态
    if not ui.is_idle():
        ui.show_error("请等待当前任务完成")
        return

    cmd.handler(args, ui)
