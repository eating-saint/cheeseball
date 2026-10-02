"""工具注册中心，集中登记所有可用工具."""

from __future__ import annotations

from cheeseball.provider import ToolDefinition
from cheeseball.tool.base import Tool


class ToolRegistry:
    """工具注册中心，集中登记、查找、导出工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具，以 tool.name 为 key。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名查找工具，不存在返回 None。"""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """返回全部已注册工具的列表。"""
        return list(self._tools.values())

    def export_definitions(
        self, readonly_only: bool = False
    ) -> list[ToolDefinition]:
        """将已注册工具转为协议无关的 ToolDefinition 列表。

        Args:
            readonly_only: True 时仅导出只读工具（Plan Mode 用）。

        发给 API 时，由各协议适配器据此转为 Anthropic/OpenAI 特定格式。
        """
        tools = self._tools.values()
        if readonly_only:
            tools = [t for t in tools if t.is_readonly]
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in tools
        ]

    def is_read_only(self, name: str) -> bool:
        """判断指定名称的工具是否为只读工具。

        Returns:
            True 表示只读工具；未知工具返回 False。
        """
        tool = self._tools.get(name)
        return tool is not None and tool.is_readonly

    def get_readonly_names(self) -> set[str]:
        """返回所有只读工具的名称集合。"""
        return {name for name, tool in self._tools.items() if tool.is_readonly}
