"""工具执行结果数据类型."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolResult:
    """工具执行结果，无论成功/失败都由此承载。

    Attributes:
        success: 执行是否成功。
        content: 成功时的产物文本；失败时的错误描述。
        error: 失败时的结构化错误码/消息，供模型理解。
        truncated: 输出是否被截断。
    """

    success: bool
    content: str
    error: str = ""
    truncated: bool = False
