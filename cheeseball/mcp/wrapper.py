"""MCP 工具适配器 —— 将远端 MCP 工具包装为 Cheeseball Tool 接口."""

from __future__ import annotations

import asyncio
import sys

from cheeseball.tool.base import Tool
from cheeseball.tool.result import ToolResult


class MCPToolWrapper(Tool):
    """将单个远端 MCP 工具包装为 Cheeseball Tool 接口。

    持有对 ClientSession 的引用，execute() 通过 session.call_tool()
    调用远端工具，转换结果为 ToolResult。
    """

    def __init__(self, server_name: str, tool_def, session) -> None:
        """初始化包装器。

        Args:
            server_name: MCP server 名（YAML key）。
            tool_def: MCP SDK list_tools() 返回的 Tool 对象，
                      有 .name、.description、.inputSchema、.annotations。
            session: 已初始化的 MCP ClientSession。
        """
        self._server_name = server_name
        self._tool_name = tool_def.name
        self._session = session
        self._tool_def = tool_def

    # ── Tool 接口属性 ──────────────────────────────────────────

    @property
    def name(self) -> str:
        """工具名，格式 mcp__<server>__<tool>。"""
        return f"mcp__{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        """给模型看的功能描述。

        远端 description 非空则直接用；空则返回含 server 名的兜底说明。
        """
        desc = getattr(self._tool_def, "description", None)
        if desc:
            return desc
        return f"MCP tool {self._tool_name} from {self._server_name}"

    @property
    def parameters(self) -> dict:
        """参数 JSON Schema，透传远端 inputSchema。

        None 时返回空 schema 兜底。
        """
        schema = getattr(self._tool_def, "inputSchema", None)
        if schema is None:
            return {"type": "object", "properties": {}}
        return schema

    @property
    def is_readonly(self) -> bool:
        """只读判定：仅 readOnlyHint 为 True 时返回 True。

        字段缺失或非法一律按有副作用处理（安全默认）。
        """
        annotations = getattr(self._tool_def, "annotations", None)
        if annotations is None:
            return False
        return getattr(annotations, "readOnlyHint", False) or False

    # ── 执行 ────────────────────────────────────────────────────

    async def execute(self, **kwargs) -> ToolResult:
        """调用远端工具，转换结果为 ToolResult。

        30s 超时，超时/协议错误转为 success=False 的结构化错误回灌给模型，
        不向 Agent Loop 抛 Python 异常。
        """
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._tool_name, kwargs),
                timeout=30,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                content="",
                error="Tool call timed out (30s)",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                content="",
                error=str(exc),
            )

        # 处理 result.content：收集 text 类型，非 text 类型计数+告警
        text_parts: list[str] = []
        non_text_count = 0
        for block in getattr(result, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            else:
                non_text_count += 1

        if non_text_count > 0:
            print(
                f"[mcp] {self._server_name}/{self._tool_name}: "
                f"{non_text_count} non-text content block(s) discarded",
                file=sys.stderr,
            )

        text = "\n".join(text_parts)

        is_error = getattr(result, "isError", False)
        if is_error:
            return ToolResult(
                success=False,
                content=text,
                error=text if text else "MCP tool returned isError",
            )

        return ToolResult(success=True, content=text)
