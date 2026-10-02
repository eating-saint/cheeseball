"""核心层：对话管理，持有消息历史和 provider（ch04 适配多轮 Agent Loop，ch05 结构化提示，ch09 会话存档）."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from cheeseball.provider import (
    BaseProvider,
    Message,
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
)
from cheeseball.tool.result import ToolResult

if TYPE_CHECKING:
    from cheeseball.session.archiver import SessionArchiver


class Conversation:
    """管理对话生命周期：消息历史、provider 调用、流式响应传递。

    用法::

        conv = Conversation(provider)
        async for event in conv.send(
            user_input="你好",
            tools=[],
            system_stable="...",
            system_environment="...",
        ):
            print(event.text)
        print(conv.messages)  # [{user}, {assistant}]
    """

    def __init__(
        self,
        provider: BaseProvider,
        archiver: SessionArchiver | None = None,
    ) -> None:
        self._provider = provider
        self._messages: list[Message] = []
        self._archiver = archiver

    @property
    def provider(self) -> BaseProvider:
        """返回持有的 provider。"""
        return self._provider

    @property
    def messages(self) -> list[Message]:
        """返回消息历史的副本。"""
        return list(self._messages)

    # ── 公开接口 ──────────────────────────────────────────────

    async def send(
        self,
        user_input: str | None = None,
        tools: list[ToolDefinition] | None = None,
        system_stable: str = "",
        system_environment: str = "",
        reminder: str = "",
    ) -> AsyncGenerator[StreamEvent, None]:
        """发送用户消息（或续接工具结果），以流式方式逐个产出 StreamEvent。

        内部流程：
        1. 若有 user_input → 将用户消息加入持久历史
        2. 构造请求消息副本，reminder 追加到副本（不写入持久历史）
        3. 组装 Request 调用 provider.stream()
        4. 收集 text 类型的文本
        5. 流结束后将 assistant 完整回复加入持久历史
        6. 所有事件都 yield 给调用方

        Args:
            user_input: 用户文本。为 None 时表示续接已有历史（多轮循环后续轮）。
            tools: 可选的工具定义列表。
            system_stable: 稳定系统提示，可缓存。
            system_environment: 环境信息，不缓存。
            reminder: <system-reminder> 文本，注入消息通道但不持久化。
        """
        if user_input is not None:
            self._messages.append(Message(role="user", content=user_input))
            if self._archiver:
                self._archiver.append_message("user", user_input)

        # 构造请求消息副本：持久历史 + reminder（仅副本，不写 self._messages）
        req_messages = list(self._messages)
        if reminder:
            req_messages.append(Message(role="user", content=reminder))

        full_text = ""
        async for event in self._provider.stream(
            Request(
                messages=req_messages,
                tools=tools,
                system_stable=system_stable,
                system_environment=system_environment,
                reminder="",  # 已在 req_messages 中注入，不重复
            )
        ):
            if event.type == "text":
                full_text += event.text
            yield event

        if full_text:
            self._messages.append(Message(role="assistant", content=full_text))

    def last_role(self) -> str:
        """返回最后一条消息的 role，空历史返回 ""。"""
        if self._messages:
            return self._messages[-1].role
        return ""

    def add_assistant(self, text: str) -> None:
        """便捷方法：追加一条 assistant 角色消息到历史。

        用于 ensure_assistant_tail——取消/出错后补 assistant 尾巴，
        保证消息历史以 assistant 结尾，避免下一轮请求 API 400。
        """
        self._messages.append(Message(role="assistant", content=text))

    def add_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """将工具调用合并到消息历史。

        若末尾已是 assistant 消息（send() 产出的文本回复），
        则将 tool_calls 合并进去，避免产生两个连续的 assistant 消息。
        否则创建新的 assistant 消息。

        同时写入 JSONL（含 tool_calls 结构化数据）。
        """
        if self._messages and self._messages[-1].role == "assistant":
            self._messages[-1].tool_calls = tool_calls
        else:
            self._messages.append(
                Message(
                    role="assistant",
                    content="",
                    tool_calls=tool_calls,
                )
            )

        # JSONL: assistant 含 tool_calls
        if self._archiver:
            last = self._messages[-1]
            self._archiver.append_message(
                "assistant",
                last.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "input": tc.arguments}
                    for tc in tool_calls
                ],
            )

    def add_tool_results(self, results: list[tuple[ToolCall, ToolResult]]) -> None:
        """将工具执行结果写入消息历史。

        以 user 角色 + tool_result 内容块的形式追加。
        格式遵循 Anthropic 协议，OpenAI 协议由适配器内部转换。

        同时写入 JSONL（每条 tool 消息独立一行）。
        """
        for tc, tr in results:
            self._messages.append(
                Message(
                    role="user",
                    content="",  # tool_result 消息没有文本 content
                    tool_result={
                        "tool_use_id": tc.id,
                        "content": tr.content if tr.success else tr.error or tr.content,
                        "is_error": not tr.success,
                    },
                )
            )
            # JSONL: tool 结果
            if self._archiver:
                content = tr.content if tr.success else tr.error or tr.content
                self._archiver.append_message(
                    "tool",
                    content,
                    tool_use_id=tc.id,
                )

    def replace_message_at(self, index: int, new_message: Message) -> None:
        """替换指定位置的消息。

        用于 offloader 在修改后的消息列表中回写替换。

        Args:
            index: 消息在 _messages 中的位置。
            new_message: 替换后的新 Message 对象。
        """
        if 0 <= index < len(self._messages):
            self._messages[index] = new_message

    def rebuild_messages(self, new_messages: list[Message]) -> None:
        """整体替换消息历史。

        用于 compact 完成后重建对话历史（摘要 + 恢复段 + 原文）。

        Args:
            new_messages: 新的消息列表。
        """
        self._messages = list(new_messages)

        # JSONL: compact 标记 + 重建
        if self._archiver:
            self._archiver.append_compact_and_rebuild(new_messages)

    def flush_assistant_to_archiver(self) -> None:
        """将最后一条 assistant 消息写入 JSONL（如果尚未写入）。

        用于 Agent Loop DONE 分支——当模型最终回复无工具调用时，
        send() 已将 assistant 消息写入 _messages 但未写入 JSONL，
        此处补写。
        """
        if not self._archiver:
            return
        if not self._messages:
            return

        last = self._messages[-1]
        if last.role != "assistant":
            return

        # 检查 archiver 最后一次写入的 role 是否已经是 assistant
        if self._archiver.last_role == "assistant":
            return  # 已写入（例如 add_tool_calls 已写入过）

        # 无 tool_calls 的 assistant 消息：补写
        self._archiver.append_message("assistant", last.content)

    def reset(self) -> None:
        """清空对话历史。"""
        self._messages.clear()
