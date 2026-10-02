"""执行命令工具."""

from __future__ import annotations

import asyncio

from cheeseball.tool.base import Tool
from cheeseball.tool.result import ToolResult

DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_CHARS = 10000


class RunCommand(Tool):
    """在项目工作目录执行 shell 命令，返回 stdout/stderr/exit_code。"""

    def __init__(self, cwd: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._cwd = cwd
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return (
            "在工作目录执行 shell 命令。返回标准输出、标准错误和退出码。"
            f"命令执行受超时约束（{self._timeout:.0f} 秒）。"
            "超时或非零退出码以结构化结果返回，不中断会话。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str) -> ToolResult:
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self._cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    stdout_bytes, stderr_bytes = await process.communicate()
                except Exception:
                    stdout_bytes, stderr_bytes = b"", b""
                partial = _decode(stdout_bytes) + _decode(stderr_bytes)
                return ToolResult(
                    success=False,
                    content=_truncate(f"[命令超时 ({self._timeout:.0f}s)]\n{partial}"),
                    error=f"TIMEOUT: command exceeded {self._timeout:.0f}s",
                )

            stdout = _decode(stdout_bytes)
            stderr = _decode(stderr_bytes)
            exit_code = process.returncode or 0

            parts = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append(f"[stderr]\n{stderr}")
            output = "\n".join(parts) if parts else "(无输出)"

            content = (
                f"[exit_code: {exit_code}]\n{output}"
                if exit_code != 0
                else output
            )

            return ToolResult(
                success=exit_code == 0,
                content=_truncate(content),
                error=stderr.strip() if exit_code != 0 else "",
                truncated=len(output) > MAX_OUTPUT_CHARS,
            )

        except Exception as e:
            return ToolResult(
                success=False,
                content=f"命令执行失败: {e}",
                error=f"EXEC_ERROR: {e}",
            )


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _truncate(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n\n[已截断: 共 {len(text)} 字符，上限 {MAX_OUTPUT_CHARS}]"
    return text
