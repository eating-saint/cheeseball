"""工具抽象基类."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mewcode.tool.result import ToolResult


class Tool(ABC):
    """所有工具的统一接口。

    新工具只需继承此类，实现 name、description、parameters 和 execute，
    然后注册到 ToolRegistry 即可被模型发现和调用。

    属性:
        is_readonly: 只读工具可并发执行且 Plan Mode 放行。默认 False，
            只读工具（read_file、glob_files、grep_files）覆盖为 True。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名，如 "read_file"。"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """给模型看的功能描述。"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """参数 JSON Schema。"""
        ...

    @property
    def is_readonly(self) -> bool:
        """只读工具可并发执行且 Plan Mode 放行。默认 False，子类覆盖返回 True。"""
        return False

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，接收具名参数，返回 ToolResult。"""
        ...
