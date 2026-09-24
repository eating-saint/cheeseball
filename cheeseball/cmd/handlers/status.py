"""/status — 纯本地命令（F13）。"""

from __future__ import annotations

from cheeseball.cmd.uictl import UICtl


def cmd_status(args: str, ui: UICtl) -> None:
    """显示运行状态：权限模式、token 入/出、工具数、记忆条目数、模型名、工作目录。

    六字段顺序固定（N8），每行 key-value 列对齐。
    """
    lines = [
        f"权限模式  : {ui.get_permission_mode()}",
        f"输入Token : {ui.get_token_input()}",
        f"输出Token : {ui.get_token_output()}",
        f"可用工具  : {ui.get_tool_count()}",
        f"记忆条目  : {ui.get_memory_count()}",
        f"当前模型  : {ui.get_model_name()}",
        f"工作目录  : {ui.get_work_dir()}",
    ]
    ui.show_info("\n".join(lines))
