"""读文件工具."""

from __future__ import annotations

from pathlib import Path

from mewcode.tool.base import Tool
from mewcode.tool.result import ToolResult

MAX_LINES = 2000


class ReadFile(Tool):
    """读取指定路径的文件内容，返回带行号的文本。"""

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd).resolve()

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "读取指定路径的文件内容。返回带行号的文本（格式: 行号:\\t内容）。"
            "可通过 offset 和 limit 参数控制读取范围。"
            "文件不存在或不可读时返回结构化错误。"
        )

    @property
    def is_readonly(self) -> bool:
        return True

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径（相对或绝对路径）",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（1-based），不指定则从第 1 行开始",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取行数，不指定则最多 {MAX_LINES} 行",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ToolResult:
        file_path = self._resolve(path)
        if file_path is None:
            return ToolResult(
                success=False,
                content=f"文件不存在或不可读: {path}",
                error=f"FILE_NOT_FOUND: {path}",
            )

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"读取文件失败: {e}",
                error=f"READ_ERROR: {e}",
            )

        lines = text.splitlines()
        total_lines = len(lines)

        # 应用 offset / limit
        start = max((offset or 1) - 1, 0)
        end = start + (limit or MAX_LINES)
        selected = lines[start:end]
        truncated = end < total_lines

        # 构建带行号输出
        result_lines = []
        for i, line_content in enumerate(selected, start=start + 1):
            result_lines.append(f"{i}:\t{line_content}")

        output = "\n".join(result_lines)
        if truncated:
            output += f"\n\n[已截断: 共 {total_lines} 行，显示了 {start + 1}-{min(end, total_lines)} 行]"

        return ToolResult(
            success=True,
            content=output,
            truncated=truncated,
        )

    def _resolve(self, path: str) -> Path | None:
        """解析路径，返回绝对 Path；不存在则返回 None。"""
        p = Path(path)
        if not p.is_absolute():
            p = self._cwd / p
        p = p.resolve()
        return p if p.exists() and p.is_file() else None
