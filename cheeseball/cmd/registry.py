"""命令注册中心（F1, G4）。

启动时加载所有命令，提供查询、列表、前缀搜索。
冲突检测在注册完所有命令后统一执行。
"""

from __future__ import annotations

from cheeseball.cmd.types import CommandDef


class CommandRegistry:
    """命令注册中心。"""

    def __init__(self) -> None:
        self._by_name: dict[str, CommandDef] = {}
        self._by_alias: dict[str, CommandDef] = {}
        self._commands: list[CommandDef] = []

    def register(self, cmd: CommandDef) -> None:
        """注册一条命令。

        Args:
            cmd: 命令定义。
        """
        self._commands.append(cmd)
        self._by_name[cmd.name] = cmd
        for alias in cmd.aliases:
            self._by_alias[alias] = cmd

    def validate(self) -> list[str]:
        """检测名字与别名冲突，返回冲突描述列表。

        空列表表示无冲突。应在所有 register 调用完成后执行。

        Returns:
            冲突描述字符串列表，每条格式为 "冲突: /{name1} 与 /{name2} 共享名字/别名 '{id}'"
        """
        conflicts: list[str] = []
        seen_names: dict[str, str] = {}   # name → 第一个注册的 cmd.name
        seen_aliases: dict[str, str] = {}  # alias → 第一个注册的 cmd.name

        for cmd in self._commands:
            # 检测主名冲突
            if cmd.name in seen_names:
                conflicts.append(
                    f"冲突: /{seen_names[cmd.name]} 与 /{cmd.name} 共享名字 '{cmd.name}'"
                )
            else:
                seen_names[cmd.name] = cmd.name
                # 主名也有可能被别的命令注册为别名
                if cmd.name in seen_aliases:
                    conflicts.append(
                        f"冲突: /{seen_aliases[cmd.name]} 的别名与 /{cmd.name} 的名字冲突 '{cmd.name}'"
                    )

            # 检测别名冲突
            for alias in cmd.aliases:
                if alias in seen_aliases:
                    conflicts.append(
                        f"冲突: /{seen_aliases[alias]} 与 /{cmd.name} 共享别名 '{alias}'"
                    )
                elif alias in seen_names:
                    conflicts.append(
                        f"冲突: /{seen_names[alias]} 的名字与 /{cmd.name} 的别名 '{alias}' 冲突"
                    )
                else:
                    seen_aliases[alias] = cmd.name

        return conflicts

    def find(self, name: str) -> CommandDef | None:
        """按命令名或别名查找（大小写不敏感）。

        Args:
            name: 命令名（已小写归一化）。

        Returns:
            CommandDef 或 None。
        """
        return self._by_name.get(name) or self._by_alias.get(name)

    def list_visible(self) -> list[CommandDef]:
        """列出所有可见命令，按名称字典序排序（F12, AC2）。

        Returns:
            过滤 hidden=True 后的命令列表。
        """
        return sorted(
            (c for c in self._commands if not c.hidden),
            key=lambda c: c.name,
        )

    def search_prefix(self, prefix: str) -> list[CommandDef]:
        """按命令名前缀搜索可见命令（F18-F19）。

        Args:
            prefix: 前缀字符串（已小写）。

        Returns:
            匹配的可见命令列表。
        """
        prefix_lower = prefix.lower()
        return [
            c for c in self.list_visible()
            if c.name.startswith(prefix_lower)
        ]
