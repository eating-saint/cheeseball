"""输入解析器（F2）。

从原始输入提取命令名和参数字符串，大小写归一。
"""

from __future__ import annotations

from cheeseball.cmd.types import ParseResult


class Parser:
    """斜杠命令解析器。"""

    @staticmethod
    def parse(text: str) -> ParseResult:
        """解析用户输入，提取命令名和参数。

        Args:
            text: 用户输入的完整文本。

        Returns:
            ParseResult，cmd_name 为空串表示非命令输入。

        Rules:
            - 不以 / 开头 → cmd_name=""，args=原文本
            - 只有 / → cmd_name=""，args=""
            - /xxx yyy → cmd_name=小写命令名，args=参数字符串
        """
        if not text.startswith("/"):
            return ParseResult(cmd_name="", args=text)

        if text == "/":
            return ParseResult(cmd_name="", args="")

        # 去掉前导 /
        rest = text[1:]
        # 首空格前为命令名，之后为参数
        parts = rest.split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        return ParseResult(cmd_name=cmd_name, args=args)
