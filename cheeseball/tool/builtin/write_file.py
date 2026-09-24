"""写文件工具."""

from __future__ import annotations

from pathlib import Path

from cheeseball.tool.base import Tool
from cheeseball.tool.result import ToolResult


class WriteFile(Tool):
    """写入（覆盖）文件，父目录不存在时自动创建。"""

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd).resolve()

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "写入（覆盖）文件。父目录不存在时自动创建。"
            "返回成功确认或结构化错误。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径（相对或绝对路径）",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文件内容",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str) -> ToolResult:
        p = Path(path)
        if not p.is_absolute():
            p = self._cwd / p
        p = p.resolve()

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            size = p.stat().st_size
            return ToolResult(
                success=True,
                content=f"文件已写入: {path} ({size} bytes)",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"写入文件失败: {e}",
                error=f"WRITE_ERROR: {e}",
            )
