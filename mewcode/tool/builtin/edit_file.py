"""改文件工具：通过唯一匹配原文片段进行替换."""

from __future__ import annotations

from pathlib import Path

from mewcode.tool.base import Tool
from mewcode.tool.result import ToolResult


class EditFile(Tool):
    """对文件中唯一匹配的原文片段进行替换。

    匹配规则：全文搜索 old_string，出现次数必须恰好为 1 才执行替换。
    匹配 0 次或 >1 次时返回结构化错误，供模型调整后重试。
    """

    def __init__(self, cwd: str) -> None:
        self._cwd = Path(cwd).resolve()

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "对文件中唯一匹配的原文片段进行替换。全文搜索 old_string："
            "恰好匹配 1 处则替换为 new_string；"
            "匹配 0 处或多于 1 处时返回清晰错误（含匹配次数），请根据错误信息调整 old_string 后重试。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要修改的文件路径（相对或绝对路径）",
                },
                "old_string": {
                    "type": "string",
                    "description": "要被替换的原文片段（需在文件中唯一匹配）",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(
        self, path: str, old_string: str, new_string: str
    ) -> ToolResult:
        p = Path(path)
        if not p.is_absolute():
            p = self._cwd / p
        p = p.resolve()

        if not p.exists() or not p.is_file():
            return ToolResult(
                success=False,
                content=f"文件不存在: {path}",
                error=f"FILE_NOT_FOUND: {path}",
            )

        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"读取文件失败: {e}",
                error=f"READ_ERROR: {e}",
            )

        count = content.count(old_string)

        if count == 0:
            return ToolResult(
                success=False,
                content=f"匹配 0 次: 未在文件中找到指定文本。请检查 old_string 是否与文件中内容完全一致（含空白字符）。",
                error="NO_MATCH: old_string not found in file",
            )

        if count > 1:
            return ToolResult(
                success=False,
                content=(
                    f"匹配 {count} 次: 原文不唯一。"
                    "请提供更多上下文使 old_string 在文件中唯一。"
                ),
                error=f"MULTIPLE_MATCHES: found {count} occurrences",
            )

        # 唯一匹配 → 替换
        new_content = content.replace(old_string, new_string, 1)
        try:
            p.write_text(new_content, encoding="utf-8")
            return ToolResult(
                success=True,
                content="已替换 1 处。",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"写入文件失败: {e}",
                error=f"WRITE_ERROR: {e}",
            )
