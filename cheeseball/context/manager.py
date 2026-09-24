"""ContextManager 门面（G8）。

对 Agent 主循环暴露的窄接口，协调所有上下文管理子模块。
3 个主要方法：offload_and_snip、compact、emergency_compact_and_retry_check。
"""

from __future__ import annotations

from cheeseball.context.circuit_breaker import CircuitBreaker
from cheeseball.context.config import auto_trigger_threshold, manual_precheck_threshold
from cheeseball.context.estimator import TokenEstimator
from cheeseball.context.file_tracker import FileReadTracker
from cheeseball.context.ledger import ReplacementLedger
from cheeseball.context.offloader import OffloadResult, offload_and_snip
from cheeseball.context.summarizer import CompactError, CompactResult, execute_compact
from cheeseball.provider import BaseProvider, ToolDefinition
from cheeseball.tool.registry import ToolRegistry


class ContextManager:
    """上下文管理器门面。

    用法::

        mgr = ContextManager(
            context_window=200000,
            session_id="1700000000-abc123",
            session_dir=Path("/project/.cheeseball/sessions/1700000000-abc123"),
            provider=provider,
            tool_registry=registry,
        )
        # 第 1 层（每轮必调）
        result = mgr.offload_and_snip(conv._messages)
        # 第 2 层（条件触发）
        if mgr.should_auto_compact():
            await mgr.compact(conv, tools, stable, env, trigger="auto")
    """

    def __init__(
        self,
        context_window: int,
        session_id: str,
        session_dir,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
    ) -> None:
        self._context_window = context_window
        self._session_id = session_id
        self._session_dir = session_dir
        self._provider = provider
        self._tool_registry = tool_registry

        # 子模块
        self._estimator = TokenEstimator()
        self._ledger = ReplacementLedger()
        self._circuit_breaker = CircuitBreaker()
        self._file_tracker = FileReadTracker()

    # ── 只读属性 ──────────────────────────────────────────────

    @property
    def estimator(self) -> TokenEstimator:
        return self._estimator

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit_breaker

    @property
    def file_tracker(self) -> FileReadTracker:
        return self._file_tracker

    # ── 第 1 层 ────────────────────────────────────────────────

    def offload_and_snip(self, messages: list, protected_from: int | None = None) -> OffloadResult:
        """委托给 offloader 原地执行第 1 层压缩（F1-F6）。

        直接修改传入的 messages（tool_result content 替换为预览体）。
        protected_from 传给 offloader，保护本轮 run() 新增的消息。

        Returns:
            OffloadResult 统计信息。
        """
        return offload_and_snip(messages, self._ledger, self._session_dir, protected_from)

    # ── 触发判断 ──────────────────────────────────────────────

    def should_auto_compact(self) -> bool:
        """判断是否应自动触发第 2 层摘要（F7, F29）。

        Returns:
            True 如果 estimator 估到超过自动阈值且熔断器未断开。
        """
        if self._circuit_breaker.tripped():
            return False
        threshold = auto_trigger_threshold(self._context_window)
        return self._estimator.estimate().total >= threshold

    def should_manual_precheck(self) -> bool:
        """手动 /compact 预检查（F23）。

        Returns:
            True 如果当前 token 估计已超过手动预检查阈值。
        """
        threshold = manual_precheck_threshold(self._context_window)
        return self._estimator.estimate().total >= threshold

    # ── 第 2 层 ────────────────────────────────────────────────

    async def compact(
        self,
        conv,
        tools: list[ToolDefinition],
        system_stable: str,
        system_environment: str,
        trigger: str,
    ) -> CompactResult:
        """执行第 2 层摘要压缩（F7, F22, F23, F25）。

        Args:
            conv: Conversation 实例。
            tools: 工具定义列表（F17: 与请求同引用）。
            system_stable: 稳定系统提示。
            system_environment: 环境信息。
            trigger: "auto" / "manual" / "emergency"。

        Returns:
            CompactResult。

        Raises:
            CompactError: 摘要失败时上抛，由调用方决定处理方式。
        """
        before = self._estimator.estimate().total
        messages = conv.messages  # 使用经过第 1 层处理后的当前消息

        try:
            result = await execute_compact(
                self._provider,
                messages,
                tools,
                system_stable,
                system_environment,
                self._file_tracker,
                self._estimator,
                trigger,
            )
        except CompactError:
            if trigger == "auto":
                self._circuit_breaker.failure()
            raise

        # 成功后重建对话
        # 构建新消息列表：摘要 user 消息 + 恢复段 + 近期原文
        from cheeseball.context.recovery import build_recovery_sections
        from cheeseball.provider import Message

        recovery = build_recovery_sections(self._file_tracker, tools)

        # 不直接写入 conv，让调用方决定（runner 负责调用 conv.rebuild_messages）
        # 但 result 中已包含足够信息
        # 重置 estimator 锚点（F14）
        self._estimator.reset_anchor()

        if trigger == "auto":
            self._circuit_breaker.success()

        return result

    async def emergency_compact_and_retry_check(
        self,
        conv,
        tools: list[ToolDefinition],
        system_stable: str,
        system_environment: str,
    ) -> bool:
        """PTL 紧急压缩 + 重试判断（F25, F25a, F26）。

        先强制跑第 1 层，再跑第 2 层（trigger="emergency"）。
        成功后检查 token 是否降至可重试水平。

        Args:
            conv: Conversation 实例。
            tools: 工具定义列表。
            system_stable: 稳定系统提示。
            system_environment: 环境信息。

        Returns:
            True 如果可以安全重试（token 降至 context_window - 3K 以下）。

        Raises:
            RuntimeError: 紧急压缩后仍超限（不可恢复，F25a）。
        """
        # F25: 先强制跑第 1 层
        self.offload_and_snip(conv._messages)

        # 再跑 compact (trigger="emergency")
        try:
            result = await self.compact(
                conv, tools, system_stable, system_environment, trigger="emergency"
            )
        except CompactError as e:
            raise RuntimeError(
                f"紧急压缩失败：{e.message}"
            ) from e

        # 重建对话历史
        from cheeseball.context.recovery import build_recovery_sections
        from cheeseball.context.summarizer import select_recent_messages
        from cheeseball.provider import Message

        recovery = build_recovery_sections(self._file_tracker, tools)
        recent = select_recent_messages(conv.messages, self._estimator)

        # 组装新消息列表：摘要 + 恢复三段 + 近期原文
        new_messages = [
            Message(role="user", content=f"[对话历史摘要]\n{result.summary_text}"),
            Message(role="user", content=f"[恢复信息]\n{recovery.file_snapshots_text}"),
            Message(role="user", content=f"[可用工具]\n{recovery.tool_list_text}"),
            Message(role="user", content=recovery.boundary_message),
        ]
        new_messages.extend(recent)

        from cheeseball.context.config import MANUAL_SAFETY_MARGIN
        conv.rebuild_messages(new_messages)
        self._estimator.reset_anchor()

        # F25a: 检查是否可重试
        current = self._estimator.estimate().total
        limit = self._context_window - 3000  # MANUAL_SAFETY_MARGIN
        if current < limit:
            return True
        raise RuntimeError(
            f"紧急压缩后 token ({current}) 仍超过安全上限 ({limit})，不可恢复"
        )
