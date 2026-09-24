"""第 1 层：危险命令黑名单。

对 run_command 的 command 参数做正则匹配，命中则返回 DENY。
仅对 run_command 工具生效，不可通过任何配置层放开。
"""

from __future__ import annotations

import re


class Blacklist:
    """内置危险命令正则列表，L1 硬拦截。"""

    _PATTERNS: list[tuple[re.Pattern, str]] = [
        (
            re.compile(r"rm\s+-rf\s+/"),
            "BLACKLIST: rm -rf /",
        ),
        (
            re.compile(r"sudo\s+rm"),
            "BLACKLIST: sudo rm",
        ),
        (
            re.compile(r":\(\)\s*\{"),
            "BLACKLIST: fork bomb",
        ),
        (
            re.compile(r"chmod\s+(-R\s+)?777\s+/"),
            "BLACKLIST: chmod 777 /",
        ),
        (
            re.compile(r"mkfs\."),
            "BLACKLIST: mkfs",
        ),
        (
            re.compile(r"dd\s+if="),
            "BLACKLIST: dd",
        ),
        (
            re.compile(r">\s*/dev/sd"),
            "BLACKLIST: redirect to block device",
        ),
    ]

    def check(self, command: str) -> tuple[bool, str]:
        """检查命令是否命中黑名单。

        Args:
            command: 待检查的 shell 命令字符串。

        Returns:
            (blocked, reason): blocked=True 表示命中黑名单，
            reason 为可读拒绝原因；未命中返回 (False, "")。
        """
        for pattern, reason in self._PATTERNS:
            if pattern.search(command):
                return True, reason
        return False, ""
