"""Agent 编排层：多轮 ReAct 循环，事件驱动，异步可取消。

状态机驱动「THINKING → EXECUTING → THINKING → ... → DONE」循环。
对外通过 AgentEvent async generator 与 UI 通信。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from mewcode.agent.collector import StreamingCollector
from mewcode.agent.events import (
    AgentEvent,
    DoneInfo,
    IterationProgress,
    PermissionChoice,
    PermissionRequest,
    PermissionResponse,
    StopReason,
    TokenUsage,
)
from mewcode.agent.executor import ToolExecutor
from mewcode.agent.state_machine import AgentState, LoopStateMachine
from mewcode.core.conversation import Conversation
from mewcode.permission import (
    PermissionEngine,
    Verdict,
    categorize,
    Mode,
)
from mewcode.prompt import SystemPromptBuilder
from mewcode.provider import BaseProvider
from mewcode.provider import PromptTooLongError
from mewcode.tool.registry import ToolRegistry

# ── 停止/收尾提示常量（内置，不可配）──
NOTICE_MAX_ITER = "（已达最大迭代轮数 {max_iter}，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"

# Plan Mode 默认执行指令
EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"


class Agent:
    """持有 provider 与注册中心，执行多轮 ReAct 循环。

    用法::

        agent = Agent(provider, registry, max_iterations=35)
        async for ev in agent.run(conv, "你好"):
            if ev.text:
                print(ev.text, end="")
            elif ev.tool_start:
                print(f"  🔧 {ev.tool_start.tool_name}")
            elif ev.tool_end:
                print(f"    → {ev.tool_end.result_summary}")
            elif ev.done:
                print(f"[{ev.done.reason.value}]")
    """

    def __init__(
        self,
        provider: BaseProvider,
        registry: ToolRegistry,
        max_iterations: int = 35,
        context_mgr=None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._max_iterations = max_iterations
        self._cancel_event = asyncio.Event()
        self._sm = LoopStateMachine(max_iterations=max_iterations)
        self._collector = StreamingCollector()
        self._executor = ToolExecutor()
        self._builder = SystemPromptBuilder()
        self._context_mgr = context_mgr  # ContextManager | None（N3: 向后兼容）
        # 权限系统（惰性初始化，首次 run() 时创建）
        self._perm_engine: PermissionEngine | None = None
        self._perm_queue: asyncio.Queue = asyncio.Queue()
        self._perm_mode = Mode.DEFAULT

    @property
    def cancelled(self) -> bool:
        """是否已被取消。"""
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        """取消当前循环。"""
        self._cancel_event.set()

    async def run(
        self,
        conv: Conversation,
        user_input: str,
        plan_mode: bool = False,
    ) -> AsyncIterator[AgentEvent]:
        """执行多轮 ReAct 循环，async generator 吐出事件流。

        Args:
            conv: 对话实例，持有消息历史和 provider。
            user_input: 用户输入文本。
            plan_mode: True 时只注入只读工具定义（/plan 模式）。

        Yields:
            AgentEvent: text/tool_start/tool_end/token_usage/iteration/done/error。
        """
        # ── 重置每次运行的 mutable 状态 ──
        self._cancel_event.clear()
        self._sm = LoopStateMachine(max_iterations=self._max_iterations)
        self._collector = StreamingCollector()
        self._executor = ToolExecutor()

        # ── 惰性初始化权限引擎 ──
        if self._perm_engine is None:
            cwd = os.getcwd()
            self._perm_engine = PermissionEngine(cwd, os.path.expanduser("~"))
        self._perm_engine.mode = self._perm_mode

        # ── 选择工具集 ──
        if plan_mode:
            tools = self._registry.export_definitions(readonly_only=True)
        else:
            tools = self._registry.export_definitions()

        # ── offload 保护线：None = 全部检测，包括 run() 内新增的消息 ──
        protected_from = None

        # ── 装配系统提示（会话内不变，只算一次）──
        stable = self._builder.build_stable()
        env = self._builder.build_environment()

        # ── [***print] 调试前缀：不调 API，把请求体存为 JSON 文件 ──
        _PRINT_PREFIX = "[***print]"
        if user_input.startswith(_PRINT_PREFIX):
            stripped = user_input[len(_PRINT_PREFIX):].strip()
            reminder = self._builder.build_reminder(
                mode="plan" if plan_mode else "normal", iteration=1,
            )

            # 构造请求体（与首轮真实发送完全一致）
            req_messages = list(conv.messages)
            if stripped:
                from mewcode.provider import Message as PMsg, Request
                req_messages.append(PMsg(role="user", content=stripped))
            if reminder:
                req_messages.append(PMsg(role="user", content=reminder))

            from mewcode.provider import Request
            body = self._provider.build_body(Request(
                messages=req_messages,
                tools=tools,
                system_stable=stable,
                system_environment=env,
                reminder="",  # 已手动注入到 req_messages
            ))

            # 写入文件
            out_dir = Path("D:/work/mewcode/testChat")
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = out_dir / f"request_{ts}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, indent=2)

            yield AgentEvent(text=f"[***print] 请求体已写入: {fname}\n")
            yield AgentEvent(done=DoneInfo(reason=StopReason.NATURAL, message=""))
            return

        is_first_round = True

        try:
            # ── 主循环 ──────────────────────────────────────
            while self._sm.state != AgentState.DONE:
                # 检查取消
                if self._cancel_event.is_set():
                    self._sm.on_cancel()
                    self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                    yield AgentEvent(
                        done=DoneInfo(
                            reason=StopReason.USER_CANCEL,
                            message=NOTICE_CANCELLED,
                        )
                    )
                    return

                # 开始新一轮
                state, reason = self._sm.start_round()
                if reason is not None:
                    # 达到迭代上限
                    notice = NOTICE_MAX_ITER.format(
                        max_iter=self._sm.max_iterations
                    )
                    self._ensure_assistant_tail(conv, notice)
                    yield AgentEvent(
                        text=notice,
                        done=DoneInfo(reason=reason, message=notice),
                    )
                    return

                # 迭代进度
                yield AgentEvent(
                    iteration=IterationProgress(
                        current=self._sm.iteration,
                        max=self._sm.max_iterations,
                    )
                )

                # ── 流式收集 ──
                stream_error = None
                try:
                    reminder = self._builder.build_reminder(
                        mode="plan" if plan_mode else "normal",
                        iteration=self._sm.iteration,
                    )

                    # ── 第 1 层预防（F6）：每次 API 请求前 offload ──
                    if self._context_mgr is not None:
                        self._context_mgr.offload_and_snip(conv._messages, protected_from)
                        self._context_mgr.estimator.add_chars(len(reminder))

                    # ── 第 2 层自动判断 ──
                    if self._context_mgr is not None and self._context_mgr.should_auto_compact():
                        yield AgentEvent(text="正在压缩上下文...\n")  # F24a
                        try:
                            result = await self._context_mgr.compact(
                                conv, tools, stable, env, trigger="auto")
                            yield AgentEvent(
                                text=f"已压缩，token 从 {result.before_tokens} "
                                     f"降至 {result.after_tokens}\n")
                        except Exception:
                            pass  # 熔断器已在 manager.compact 内部记录

                    # ── PTL 紧急压缩重试 ──
                    emergency_retried = False  # F26: 每次迭代最多重试一次
                    try:
                        async for ev in self._collector.collect(
                            conv,
                            user_input=user_input if is_first_round else None,
                            tools=tools,
                            system_stable=stable,
                            system_environment=env,
                            reminder=reminder,
                        ):
                            yield ev
                            # 流式期间检查取消
                            if self._cancel_event.is_set():
                                break
                    except PromptTooLongError:
                        if not emergency_retried and self._context_mgr is not None:
                            emergency_retried = True
                            yield AgentEvent(text="上下文撞墙，自动压缩中...\n")  # F24b
                            can_retry = await self._context_mgr.emergency_compact_and_retry_check(
                                conv, tools, stable, env)
                            if can_retry:
                                # 重试一次（F26）
                                async for ev in self._collector.collect(
                                    conv,
                                    user_input=user_input if is_first_round else None,
                                    tools=tools,
                                    system_stable=stable,
                                    system_environment=env,
                                    reminder=reminder,
                                ):
                                    yield ev
                            else:
                                raise
                        else:
                            raise  # 已重试过或无 context_mgr → 上抛

                    is_first_round = False

                    # ── 产出 token 用量（含缓存字段）──
                    if self._collector.last_usage is not None:
                        u = self._collector.last_usage
                        yield AgentEvent(
                            token_usage=TokenUsage(
                                input_tokens=u.input_tokens,
                                output_tokens=u.output_tokens,
                                cache_write_tokens=u.cache_write_tokens,
                                cache_read_tokens=u.cache_read_tokens,
                            )
                        )
                        # F14: 每次 API 请求后更新 token 估算锚点
                        if self._context_mgr is not None:
                            self._context_mgr.estimator.update_anchor(u)
                except Exception as exc:
                    stream_error = exc

                # ── 流结束时检查取消 ──
                if self._cancel_event.is_set():
                    self._sm.on_cancel()
                    self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                    yield AgentEvent(
                        done=DoneInfo(
                            reason=StopReason.USER_CANCEL,
                            message=NOTICE_CANCELLED,
                        )
                    )
                    return

                # ── 流出错处理 ──
                if stream_error is not None:
                    state, reason = self._sm.on_stream_error()
                    self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                    yield AgentEvent(
                        error=str(stream_error),
                        done=DoneInfo(reason=reason, message=NOTICE_STREAM_ERR),
                    )
                    return

                # ── 收集结果判断 ──
                collected = self._collector.collected_round
                if collected is None:
                    # 流被中断（取消等），已在上方处理
                    continue

                has_tool_calls = len(collected.tool_calls) > 0
                state = self._sm.on_stream_done(has_tool_calls)

                if state == AgentState.EXECUTING:
                    # ── 权限检查（在 executor 之前）──
                    allowed_calls = []
                    denied_results: dict[str, tuple] = {}
                    tool_results: list[tuple] = []

                    for tc in collected.tool_calls:
                        tool = self._registry.get(tc.name)
                        if tool is None:
                            # 未知工具：跳过权限检查，直接 allow（executor 会返回 UNKNOWN_TOOL 错误）
                            allowed_calls.append(tc)
                            continue

                        category = categorize(tool)
                        result = self._perm_engine.check(
                            tc.name, tc.arguments, category
                        )

                        if result.verdict == Verdict.ALLOW:
                            allowed_calls.append(tc)

                        elif result.verdict == Verdict.DENY:
                            from mewcode.tool.result import ToolResult
                            denied_results[tc.id] = (
                                tc,
                                ToolResult(
                                    success=False,
                                    content="[权限拒绝]",
                                    error=result.reason,
                                ),
                            )

                        elif result.verdict == Verdict.ASK:
                            # yield PermissionRequest，暂停 Loop 等用户决定
                            args_preview = _args_preview_for_tc(tc)
                            yield AgentEvent(
                                permission_request=PermissionRequest(
                                    tool_name=tc.name,
                                    args_preview=args_preview,
                                    reason=result.reason,
                                )
                            )

                            # 等待用户通过 TUI 回传选择
                            try:
                                response: PermissionResponse = await asyncio.wait_for(
                                    self._perm_queue.get(), timeout=120
                                )
                            except asyncio.TimeoutError:
                                # 超时默认拒绝
                                from mewcode.tool.result import ToolResult
                                denied_results[tc.id] = (
                                    tc,
                                    ToolResult(
                                        success=False,
                                        content="[权限拒绝]",
                                        error="ASK_TIMEOUT: 用户 120s 未响应，默认拒绝",
                                    ),
                                )
                                continue

                            if response.choice == PermissionChoice.ALLOW_ONCE:
                                allowed_calls.append(tc)
                            elif response.choice == PermissionChoice.ALLOW_ALWAYS:
                                allowed_calls.append(tc)
                                # 提取 primary_arg 并写入永久规则
                                primary_arg = _extract_primary_arg(tc)
                                self._perm_engine.add_permanent_rule(
                                    tc.name, primary_arg
                                )
                            elif response.choice == PermissionChoice.DENY_ONCE:
                                from mewcode.tool.result import ToolResult
                                denied_results[tc.id] = (
                                    tc,
                                    ToolResult(
                                        success=False,
                                        content="[权限拒绝]",
                                        error="ASK_DENIED: 用户拒绝",
                                    ),
                                )

                    # ── 执行放行的工具调用 ──
                    if allowed_calls:
                        async for ev in self._executor.execute(
                            allowed_calls,
                            self._registry,
                            self._cancel_event,
                        ):
                            yield ev

                    # ── 合并结果（按原始顺序）──
                    for tc in collected.tool_calls:
                        if tc.id in denied_results:
                            tool_results.append(denied_results[tc.id])
                        else:
                            # 从 executor.results 中找到对应结果
                            for er_tc, er_tr in self._executor.results:
                                if er_tc.id == tc.id:
                                    tool_results.append((er_tc, er_tr))
                                    break

                    # ── 文件读取追踪（F19, F19a）──
                    # 在 add_tool_results 之前记录 read_file 结果，
                    # 保证下一次 ManageContext 可观察到本轮 ReadFile 记录。
                    if self._context_mgr is not None:
                        for tc, tr in tool_results:
                            if tr.success and tc.name == "read_file":
                                path = tc.arguments.get("path", "")
                                if path:
                                    try:
                                        raw = Path(path).read_bytes()
                                        self._context_mgr.file_tracker.record(path, raw)
                                    except Exception:
                                        pass  # 追踪失败不阻塞主流程

                    # 回灌工具调用和结果
                    conv.add_tool_calls(collected.tool_calls)
                    conv.add_tool_results(tool_results)

                    # 统计未知工具
                    unknown_count = sum(
                        1
                        for tc in collected.tool_calls
                        if self._registry.get(tc.name) is None
                    )
                    state, reason = self._sm.on_tools_executed(
                        unknown_count, len(collected.tool_calls)
                    )

                    if reason is not None:
                        self._ensure_assistant_tail(
                            conv, NOTICE_UNKNOWN_TOOLS
                        )
                        yield AgentEvent(
                            text=NOTICE_UNKNOWN_TOOLS,
                            done=DoneInfo(
                                reason=reason,
                                message=NOTICE_UNKNOWN_TOOLS,
                            ),
                        )
                        return

                elif state == AgentState.DONE:
                    # 自然完成（模型不再请求工具）
                    # ch09: 补写无工具调用的 assistant 消息到 JSONL
                    conv.flush_assistant_to_archiver()
                    yield AgentEvent(
                        done=DoneInfo(
                            reason=StopReason.NATURAL,
                            message="",
                        )
                    )
                    return

        except asyncio.CancelledError:
            # Task 被 cancel() → 标记取消
            self._sm.on_cancel()
            self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
            yield AgentEvent(
                done=DoneInfo(
                    reason=StopReason.USER_CANCEL,
                    message=NOTICE_CANCELLED,
                )
            )

    # ── 权限模式切换 ──────────────────────────────────────────

    def switch_permission_mode(self, direction: int) -> Mode:
        """切换权限模式。

        Args:
            direction: +1 下一档, -1 上一档。

        Returns:
            切换后的新模式。
        """
        if self._perm_engine is not None:
            self._perm_mode = self._perm_engine.switch_mode_cycle(direction)
        else:
            # 引擎尚未初始化时手动循环
            self._perm_mode = _cycle_mode_fallback(self._perm_mode, direction)
        return self._perm_mode

    # ── 内部方法 ──────────────────────────────────────────────

    def _ensure_assistant_tail(
        self, conv: Conversation, fallback_text: str
    ) -> None:
        """保证对话历史以 assistant 角色结尾。

        取消/出错/迭代上限后，历史末尾可能为 user 或 tool 角色，
        导致下一轮请求 API 400。补 assistant 文本保证角色交替。

        Args:
            conv: 对话实例。
            fallback_text: 末尾不为 assistant 时追加的文本。
        """
        if conv.last_role() != "assistant":
            conv.add_assistant(fallback_text)


# ── 权限辅助 ──────────────────────────────────────────────────────


def _args_preview_for_tc(tc) -> str:
    """从 ToolCall 提取参数预览字符串。"""
    if not tc.arguments:
        return ""
    for key in ("command", "path", "pattern"):
        if key in tc.arguments:
            val = str(tc.arguments[key])
            if len(val) > 60:
                val = val[:57] + "..."
            return val
    # 回退：取第一个参数值
    first_val = next(iter(tc.arguments.values()), "")
    val = str(first_val)
    return val[:60] if len(val) > 60 else val


def _extract_primary_arg(tc) -> str:
    """从 ToolCall 提取第一个关键参数（command 或 path）。"""
    if "command" in tc.arguments:
        return str(tc.arguments["command"])
    if "path" in tc.arguments:
        return str(tc.arguments["path"])
    return ""


def _cycle_mode_fallback(mode: Mode, direction: int) -> Mode:
    """引擎未初始化时手动循环模式。"""
    from mewcode.permission import cycle_mode
    return cycle_mode(mode, direction)
