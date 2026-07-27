"""/help — 纯本地命令（F12）。"""

from __future__ import annotations

from mewcode.cmd.registry import CommandRegistry
from mewcode.cmd.uictl import UICtl

# 模块级变量，在注册时由 main.py 注入
_registry: CommandRegistry | None = None


def set_registry(registry: CommandRegistry) -> None:
    """注入 CommandRegistry 引用，供 /help handler 使用。"""
    global _registry
    _registry = registry


def cmd_help(args: str, ui: UICtl) -> None:
    """显示命令帮助。

    无参数: 列出所有可见命令的「名字 + 描述」两列对齐。
    带参数: 显示指定命令的详细用法。
    """
    registry = _registry
    if registry is None:
        ui.show_error("命令注册中心未初始化")
        return

    name = args.strip()
    if name:
        # 显示指定命令的详细用法
        cmd = registry.find(name.lower())
        if cmd is None:
            ui.show_error(f"未知命令: /{name}。输入 /help 查看可用命令")
            return
        lines = [
            f"/{cmd.name} — {cmd.description}",
        ]
        if cmd.aliases:
            aliases_str = ", ".join(f"/{a}" for a in cmd.aliases)
            lines.append(f"别名: {aliases_str}")
        if cmd.usage:
            lines.append(f"用法: {cmd.usage}")
        if cmd.params:
            lines.append(f"参数: {cmd.params}")
        ui.show_info("\n".join(lines))
    else:
        # 列出所有可见命令（字典序）
        commands = registry.list_visible()
        if not commands:
            ui.show_info("无可用命令")
            return
        max_name_len = max(len(c.name) for c in commands)
        lines = ["可用命令:"]
        for cmd in commands:
            lines.append(f"  /{cmd.name:<{max_name_len}}  {cmd.description}")
        lines.append("")
        lines.append("输入 /help <命令名> 查看详细用法")
        ui.show_info("\n".join(lines))
