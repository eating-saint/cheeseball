"""保序分批工具执行器：连续只读工具并发 gather，有副作用的串行执行。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from mewcode.agent.events import AgentEvent, ToolEnd, ToolStart
from mewcode.provider import ToolCall
from mewcode.tool.registry import ToolRegistry
from mewcode.tool.result import ToolResult

# 单工具执行超时（秒）
TOOL_TIMEOUT = 30


class ToolExecutor:
    """接收工具调用列表，按 is_readonly 分批执行，结果按原顺序产出。

    分批策略：
    - 连续只读工具 → asyncio.gather 并发
    - 有副作用的工具 → 逐个 await 串行
    - 保持模型给出的相对顺序不变

    用法::

        executor = ToolExecutor()
        async for ev in executor.execute(tool_calls, registry):
            if ev.tool_start:
                print(f"Running: {ev.tool_start.tool_name}")
            elif ev.tool_end:
                print(f"Done: {ev.tool_end.result_summary}")
        for tc, result in executor.results:
            print(f"{tc.name}: {result.content}")
    """

    def __init__(self) -> None:
        self.results: list[tuple[ToolCall, ToolResult]] = []

    async def execute(
        self,
        tool_calls: list[ToolCall],
        registry: ToolRegistry,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """执行工具调用列表，按只读/写分批。

        Args:
            tool_calls: 待执行的工具调用列表。
            registry: 工具注册中心，用于查找工具和判断 is_readonly。
            cancel_event: 可选的取消事件，set 后停止执行剩余工具。

        Yields:
            AgentEvent: tool_start / tool_end 事件。
        """
        n = len(tool_calls)
        if n == 0:
            return

        results: list[tuple[ToolCall, ToolResult] | None] = [None] * n
        i = 0

        while i < n:
            # ── 检查取消 ──
            if cancel_event and cancel_event.is_set():
                # 为未执行的工具填充取消占位结果
                for k in range(i, n):
                    tc = tool_calls[k]
                    results[k] = (
                        tc,
                        ToolResult(
                            success=False,
                            content="（已取消）",
                            error="CANCELLED",
                        ),
                    )
                self.results = [r for r in results if r is not None]
                return

            tool = registry.get(tool_calls[i].name)

            if tool is not None and tool.is_readonly:
                # ── 只读工具：扫描连续只读段 ──
                j = i
                while j < n:
                    t = registry.get(tool_calls[j].name)
                    if t is None or not t.is_readonly:
                        break
                    j += 1

                batch = list(range(i, j))

                # yield 全部 tool_start
                for idx in batch:
                    tc = tool_calls[idx]
                    args_preview = _format_args_preview(tc.arguments)
                    yield AgentEvent(
                        tool_start=ToolStart(
                            tool_id=tc.id,
                            tool_name=tc.name,
                            args_preview=args_preview,
                        )
                    )

                # 并发执行
                gather_results = await asyncio.gather(
                    *[_run_one(tool_calls[idx], registry, cancel_event) for idx in batch],
                    return_exceptions=True,
                )

                # yield 全部 tool_end（按原顺序）
                for idx in batch:
                    tc = tool_calls[idx]
                    raw = gather_results[idx - i]
                    if isinstance(raw, BaseException):
                        tr = ToolResult(
                            success=False,
                            content=f"工具执行异常: {raw}",
                            error=f"TOOL_ERROR: {raw}",
                        )
                    else:
                        tr = raw
                    results[idx] = (tc, tr)
                    summary = _truncate_summary(
                        tr.content if tr.success else (tr.error or tr.content), 300
                    )
                    yield AgentEvent(
                        tool_end=ToolEnd(
                            tool_id=tc.id,
                            tool_name=tc.name,
                            result_summary=summary,
                            is_error=not tr.success,
                        )
                    )

                i = j

            else:
                # ── 副作用工具：串行执行 ──
                tc = tool_calls[i]
                args_preview = _format_args_preview(tc.arguments)
                yield AgentEvent(
                    tool_start=ToolStart(
                        tool_id=tc.id,
                        tool_name=tc.name,
                        args_preview=args_preview,
                    )
                )

                tr = await _run_one(tc, registry, cancel_event)
                results[i] = (tc, tr)
                summary = _truncate_summary(
                    tr.content if tr.success else (tr.error or tr.content), 300
                )
                yield AgentEvent(
                    tool_end=ToolEnd(
                        tool_id=tc.id,
                        tool_name=tc.name,
                        result_summary=summary,
                        is_error=not tr.success,
                    )
                )

                i += 1

        self.results = [r for r in results if r is not None]


async def _run_one(
    tc: ToolCall,
    registry: ToolRegistry,
    cancel_event: asyncio.Event | None = None,
) -> ToolResult:
    """执行单个工具调用，带超时和取消检查。

    Args:
        tc: 工具调用。
        registry: 工具注册中心。
        cancel_event: 可选的取消事件。

    Returns:
        ToolResult: 执行结果（成功或失败）。
    """
    # 检查取消
    if cancel_event and cancel_event.is_set():
        return ToolResult(
            success=False,
            content="（已取消）",
            error="CANCELLED",
        )

    tool = registry.get(tc.name)
    if tool is None:
        return ToolResult(
            success=False,
            content=f"未知工具: {tc.name}",
            error=f"UNKNOWN_TOOL: {tc.name}",
        )

    try:
        result = await asyncio.wait_for(
            tool.execute(**tc.arguments),
            timeout=TOOL_TIMEOUT,
        )
        return result
    except asyncio.TimeoutError:
        return ToolResult(
            success=False,
            content=f"工具执行超时（{TOOL_TIMEOUT}s）: {tc.name}",
            error=f"TIMEOUT: {tc.name}",
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            content=f"工具执行异常: {exc}",
            error=f"TOOL_ERROR: {exc}",
        )


def _format_args_preview(args: dict) -> str:
    """从参数字典中提取关键字段作为预览字符串。"""
    if not args:
        return ""
    key_params = []
    for key in ("path", "command", "pattern", "old_string", "new_string"):
        if key in args:
            val = str(args[key])
            if len(val) > 60:
                val = val[:57] + "..."
            key_params.append(val)
    if key_params:
        return ", ".join(key_params)
    items = list(args.items())[:2]
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in items)


def _truncate_summary(text: str, max_len: int) -> str:
    """截断长文本用于摘要显示。"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
