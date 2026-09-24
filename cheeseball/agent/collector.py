"""流式双路收集器：封装一轮 LLM 调用的实时 yield + 累积收集。

仅 yield 文本增量（AgentEvent.text）。工具调用事件由 executor 产出，
避免 collector 和 executor 各发一遍 tool_start/tool_end 造成重复。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from cheeseball.agent.events import AgentEvent, CollectedRound, TokenUsage
from cheeseball.core.conversation import Conversation
from cheeseball.provider import ToolCall, ToolDefinition, Usage


class StreamingCollector:
    """封装一轮 LLM 调用的双路收集。

    一路实时 yield AgentEvent.text，供 UI 即时渲染；
    一路累积完整文本和完整 ToolCall 列表，供循环判断下一步。

    用法::

        collector = StreamingCollector()
        async for ev in collector.collect(
            conv, user_input="你好", tools=[], system_stable="...", ...
        ):
            print(ev.text)  # 实时显示
        round = collector.collected_round  # 累积结果
        usage = collector.last_usage       # token 用量（含缓存字段）
    """

    def __init__(self) -> None:
        self.collected_round: CollectedRound | None = None
        self.last_usage: Usage | None = None

    async def collect(
        self,
        conv: Conversation,
        user_input: str | None,
        tools: list[ToolDefinition],
        system_stable: str = "",
        system_environment: str = "",
        reminder: str = "",
    ) -> AsyncIterator[AgentEvent]:
        """执行一轮 LLM 调用，双路收集。

        Args:
            conv: 对话实例。
            user_input: 用户文本，为 None 时表示续接已有历史。
            tools: 本轮的 ToolDefinition 列表。
            system_stable: 稳定系统提示，可缓存。
            system_environment: 环境信息，不缓存。
            reminder: <system-reminder> 文本，注入消息通道。

        Yields:
            AgentEvent.text: 文本增量（thinking 和 content 统一走文本通道）。
            收集完毕后可通过 collected_round 获取累积结果，
            通过 last_usage 获取 token 用量。
        """
        full_text = ""
        collected_calls: list[ToolCall] = []
        # 追踪正在进行中的 tool_call（按 tool_id 索引）
        pending: dict[str, dict] = {}  # tool_id → {name, arguments_str}
        self.last_usage = None

        # ⚠ 不能 break —— send() 在 yield done 之后还要 append assistant 消息，
        #    提前 break 会让 send() 的清理代码永远不执行，导致历史不完整。
        async for se in conv.send(
            user_input=user_input,
            tools=tools,
            system_stable=system_stable,
            system_environment=system_environment,
            reminder=reminder,
        ):
            # ── 文本增量（thinking 和 content 统一走文本通道）──
            if se.type in ("text", "thinking"):
                full_text += se.text
                yield AgentEvent(text=se.text)

            # ── 工具调用：静默累积，不 yield（由 executor 统一产出事件）──
            elif se.type == "tool_start":
                pending[se.tool_id] = {
                    "name": se.tool_name,
                    "arguments_str": "",
                }

            elif se.type == "tool_delta":
                if se.tool_id in pending:
                    pending[se.tool_id]["arguments_str"] += se.text

            elif se.type == "tool_end":
                if se.tool_id in pending:
                    info = pending.pop(se.tool_id)
                    args = se.tool_arguments_sofar or {}
                    collected_calls.append(
                        ToolCall(
                            id=se.tool_id,
                            name=info["name"],
                            arguments=args,
                        )
                    )

            # done 事件 → 捕获 usage，不做其他事，让 send() 自然完成清理
            elif se.type == "done":
                self.last_usage = se.usage

        # 收集完成，写入结果
        self.collected_round = CollectedRound(
            text=full_text,
            tool_calls=collected_calls,
        )
