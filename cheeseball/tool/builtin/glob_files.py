"""按模式找文件工具."""

from __future__ import annotations

from pathlib import Path

from cheeseball.tool.base import Tool
from cheeseball.tool.result import ToolResult

MAX_RESULTS = 500


class GlobFiles(Tool):
    """按 glob 模式查找文件，返回匹配的文件路径列表。"""

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd).resolve()

    @property
    def name(self) -> str:
        return "glob_files"

    @property
    def description(self) -> str:
        return (
            "按 glob 模式查找文件，返回匹配的文件路径列表。"
            "支持 ** 递归匹配（如 **/*.py）。"
        )

    @property
    def is_readonly(self) -> bool:
        return True

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 '**/*.py' 或 '*.txt'",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str) -> ToolResult:
        try:
            # ** 模式用 rglob，其他用 glob
            if "**" in pattern:
                matches = list(self._cwd.rglob(pattern))
            else:
                matches = list(self._cwd.glob(pattern))

            # 转为相对路径
            paths = []
            for m in matches:
                try:
                    paths.append(str(m.relative_to(self._cwd)))
                except ValueError:
                    paths.append(str(m))

            truncated = len(paths) > MAX_RESULTS
            if truncated:
                paths = paths[:MAX_RESULTS]

            if not paths:
                return ToolResult(
                    success=True,
                    content=f"(未找到匹配 '{pattern}' 的文件)",
                )

            output = "\n".join(paths)
            if truncated:
                output += f"\n\n[已截断: 共 {len(matches)} 条结果，显示前 {MAX_RESULTS} 条]"

            return ToolResult(
                success=True,
                content=output,
                truncated=truncated,
            )

        except Exception as e:
            return ToolResult(
                success=False,
                content=f"glob 搜索失败: {e}",
                error=f"GLOB_ERROR: {e}",
            )
