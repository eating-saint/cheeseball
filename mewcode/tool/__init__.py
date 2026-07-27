"""工具层：统一工具抽象、注册中心、内置工具集."""

from __future__ import annotations

from mewcode.tool.builtin.edit_file import EditFile
from mewcode.tool.builtin.glob_files import GlobFiles
from mewcode.tool.builtin.grep_files import GrepFiles
from mewcode.tool.builtin.read_file import ReadFile
from mewcode.tool.builtin.run_command import RunCommand
from mewcode.tool.builtin.write_file import WriteFile
from mewcode.tool.registry import ToolRegistry


def new_default_registry(cwd: str) -> ToolRegistry:
    """创建默认的工具注册中心，登记全部 6 个核心工具。

    Args:
        cwd: 工作目录路径。

    Returns:
        已注册全部内置工具的 ToolRegistry 实例。
    """
    registry = ToolRegistry()
    registry.register(ReadFile(cwd))
    registry.register(WriteFile(cwd))
    registry.register(EditFile(cwd))
    registry.register(RunCommand(cwd))
    registry.register(GlobFiles(cwd))
    registry.register(GrepFiles(cwd))
    return registry
