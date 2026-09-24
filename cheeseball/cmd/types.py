"""命令系统核心类型定义（F1, F2, F3）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from cheeseball.cmd.uictl import UICtl


class CommandKind(Enum):
    """命令执行模式（F3）。"""
    LOCAL = auto()    # 纯本地：不调 LLM，不改 UI 状态
    UI = auto()       # 影响界面：改 TUI/会话状态，不调 LLM
    PROMPT = auto()   # 提示词注入：预设文本送入 Agent


@dataclass
class CommandDef:
    """命令元数据（F1）。

    每一条命令登记：名称、别名列表、简短描述、用法示例、命令类型、
    可选参数提示、是否隐藏、处理函数。
    """
    name: str                        # 命令名（不含 /），如 "status"
    kind: CommandKind                # 执行模式
    description: str                 # 一句描述，用于 /help 和补全菜单
    handler: Callable                # (args: str, ui: UICtl) -> None
    aliases: tuple[str, ...] = ()    # 别名列表
    usage: str = ""                  # 用法示例，如 "/do [指令]"
    params: str = ""                 # 参数提示文本
    hidden: bool = False             # True 则不出现在 /help 和补全菜单（F22）


@dataclass
class ParseResult:
    """输入解析结果（F2）。"""
    cmd_name: str       # 归一化后的命令名（小写），空串表示非命令
    args: str           # 参数字符串（原样保留）
