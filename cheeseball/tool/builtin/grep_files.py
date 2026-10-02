"""搜代码内容工具."""

from __future__ import annotations

import re
from pathlib import Path

from cheeseball.tool.base import Tool
from cheeseball.tool.result import ToolResult

MAX_MATCHES = 200
# 跳过这些目录
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".claude"}
# 只搜索文本文件（按扩展名或常见文本类型）
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala", ".cs", ".sh",
    ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".txt", ".md", ".rst", ".cfg", ".ini", ".toml", ".yaml", ".yml", ".json",
    ".xml", ".html", ".css", ".scss", ".less", ".svg", ".csv", ".tsv",
    ".dockerfile", ".makefile", ".cmake", ".gradle", ".sql", ".r", ".lua",
    ".vim", ".el", ".conf",
}


class GrepFiles(Tool):
    """在文件内容中搜索正则表达式，返回命中位置（文件/行号/内容）。"""

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd).resolve()

    @property
    def name(self) -> str:
        return "grep_files"

    @property
    def description(self) -> str:
        return (
            "在文件内容中按正则表达式搜索，返回命中位置（文件路径、行号、行内容）。"
            "可通过 path 参数限制搜索范围。"
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
                    "description": "搜索的正则表达式模式",
                },
                "path": {
                    "type": "string",
                    "description": "限制搜索的目录或文件路径（相对于工作目录），默认为项目根目录",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, path: str = ".") -> ToolResult:
        search_root = self._cwd / path if path != "." else self._cwd
        search_root = search_root.resolve()

        if not search_root.exists():
            return ToolResult(
                success=False,
                content=f"路径不存在: {path}",
                error=f"PATH_NOT_FOUND: {path}",
            )

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(
                success=False,
                content=f"正则表达式无效: {e}",
                error=f"REGEX_ERROR: {e}",
            )

        results: list[tuple[str, int, str]] = []
        truncated = False
        files_scanned = 0

        try:
            if search_root.is_file():
                entries = [search_root]
            else:
                entries = list(search_root.rglob("*"))

            for entry in entries:
                if not entry.is_file():
                    continue
                # 跳过非文本文件
                if entry.suffix.lower() not in TEXT_EXTENSIONS:
                    # 对一些无后缀但可能是文本的文件也尝试
                    if entry.suffix:
                        continue
                # 跳过隐藏目录
                parts = entry.parts
                if any(p in SKIP_DIRS for p in parts):
                    continue

                files_scanned += 1

                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                for line_no, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel_path = str(entry.relative_to(self._cwd))
                        results.append((rel_path, line_no, line.strip()))
                        if len(results) >= MAX_MATCHES:
                            truncated = True
                            break

                if truncated:
                    break

        except Exception as e:
            return ToolResult(
                success=False,
                content=f"搜索出错: {e}",
                error=f"GREP_ERROR: {e}",
            )

        if not results:
            return ToolResult(
                success=True,
                content=f"(在 {files_scanned} 个文件中未找到匹配 '{pattern}' 的内容)",
            )

        output_lines = []
        for file_path, line_no, line_content in results:
            output_lines.append(f"{file_path}:{line_no}: {line_content}")

        output = "\n".join(output_lines)
        if truncated:
            output += f"\n\n[已截断: 命中数超 {MAX_MATCHES} 条上限]"

        return ToolResult(
            success=True,
            content=output,
            truncated=truncated,
        )
