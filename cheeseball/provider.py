"""Provider 层：统一 LLM 后端抽象 + Anthropic/OpenAI 实现（ch03 扩展工具调用，ch05 结构化提示与缓存）."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal

import httpx

from cheeseball.config.loader import ProviderConfig


# ── 上下文超限异常 ────────────────────────────────────────────


class PromptTooLongError(RuntimeError):
    """上下文超限错误，触发紧急压缩（F25）。"""


# ── 协议无关工具类型 ──────────────────────────────────────────


@dataclass
class ToolDefinition:
    """工具定义（协议无关），发给 API 时由适配器转为对应格式。

    Attributes:
        name: 工具名，如 "read_file"。
        description: 给模型看的功能描述。
        parameters: JSON Schema 参数定义。
    """

    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    """已解析的工具调用。

    Attributes:
        id: API 分配的调用 ID。
        name: 工具名。
        arguments: 已解析的参数字典（JSON → dict）。
    """

    id: str
    name: str
    arguments: dict


# ── 统一数据类型 ──────────────────────────────────────────────


@dataclass
class Usage:
    """一次 LLM 请求的 token 用量统计。

    Attributes:
        input_tokens: 输入 token 数（含缓存命中和未命中部分）。
        output_tokens: 输出 token 数。
        cache_write_tokens: 本次请求新写入缓存的 token 数。
        cache_read_tokens: 本次请求从缓存命中的 token 数。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class Request:
    """一次 LLM 请求的完整入参。

    Attributes:
        messages: 对话历史消息列表。
        tools: 可用的工具定义列表（None 表示无工具）。
        system_stable: 稳定系统提示模块拼接，可缓存。
        system_environment: 环境信息（OS、日期、cwd），不缓存。
        reminder: <system-reminder> 补充指令文本，注入消息通道。
    """

    messages: list[Message]
    tools: list[ToolDefinition] | None = None
    system_stable: str = ""
    system_environment: str = ""
    reminder: str = ""


@dataclass
class StreamEvent:
    """流式事件，覆盖文本、思考和工具调用等所有事件类型。

    Attributes:
        type: 事件类型。
            - "thinking": 思考增量（Claude extended thinking）
            - "text": 正文文本增量
            - "tool_start": 工具调用开始（含 tool_id + tool_name）
            - "tool_delta": 工具参数 JSON 片段增量
            - "tool_end": 工具调用参数完整（含 tool_arguments_sofar）
            - "done": 流结束（可携带 usage 信息）
        text: 文本内容（text/thinking/tool_delta 时填充）。
        tool_id: 工具调用 ID（tool_start/tool_delta/tool_end 时填充）。
        tool_name: 工具名（tool_start 时填充）。
        tool_arguments_sofar: 目前已累积的参数 dict（tool_delta/tool_end 时填充）。
        usage: token 用量（done 事件时填充）。
    """

    type: Literal["thinking", "text", "tool_start", "tool_delta", "tool_end", "done"]
    text: str = ""
    tool_id: str = ""
    tool_name: str = ""
    tool_arguments_sofar: dict | None = None
    usage: Usage | None = None


@dataclass
class Message:
    """对话消息.

    Attributes:
        role: 消息角色（user 或 assistant）。
        content: 消息文本内容。
        tool_calls: 工具调用列表（assistant 消息可选附加）。
        tool_result: 工具执行结果（user 消息可选附加）。
    """

    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_result: dict | None = None


# ── 抽象基类 ──────────────────────────────────────────────────


class BaseProvider(ABC):
    """LLM 后端的统一抽象接口。所有 provider 必须实现 stream()。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def stream(
        self,
        request: Request,
    ) -> AsyncGenerator[StreamEvent, None]:
        """以 SSE 流调用 LLM API，逐 event yield 统一格式的 StreamEvent。

        Args:
            request: 封装本次请求全部参数（消息、工具、提示分区）。
        """
        ...


# ── 工厂函数 ──────────────────────────────────────────────────


def create_provider(config: ProviderConfig) -> BaseProvider:
    """根据 config.protocol 返回对应的 Provider 实例。

    Raises:
        ValueError: 不支持的 protocol。
    """
    protocol = config.protocol.lower()
    if protocol == "anthropic":
        return AnthropicProvider(config)
    elif protocol == "openai":
        return OpenAIProvider(config)
    else:
        raise ValueError(
            f"不支持的协议: {config.protocol}（目前支持 anthropic 和 openai）"
        )


# ── Anthropic 后端 ────────────────────────────────────────────


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API SSE 流。

    端点: POST {base_url}/v1/messages
    支持 extended thinking 和 tool use。
    缓存策略：stable 块打 cache_control 断点，env 块不打。
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        base = config.base_url.rstrip("/")
        self.url = f"{base}/v1/messages"
        self.headers = {
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def build_body(self, request: Request) -> dict:
        """返回即将发送给 Anthropic API 的请求体 dict。"""
        system_blocks: list[dict] = []
        if request.system_stable:
            system_blocks.append({
                "type": "text",
                "text": request.system_stable,
                "cache_control": {"type": "ephemeral"},
            })
        if request.system_environment:
            system_blocks.append({
                "type": "text",
                "text": request.system_environment,
            })

        api_messages = _format_messages_anthropic(request.messages)
        if request.reminder:
            api_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": request.reminder}],
            })

        body: dict = {
            "model": self.config.model,
            "max_tokens": 4096,
            "messages": api_messages,
            "stream": True,
        }
        if system_blocks:
            body["system"] = system_blocks
        if self.config.model.startswith("claude"):
            body["thinking"] = {"type": "enabled", "budget_tokens": 2000}
        if request.tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
        return body

    async def stream(
        self,
        request: Request,
    ) -> AsyncGenerator[StreamEvent, None]:
        body = self.build_body(request)

        # 追踪工具调用累积状态
        tool_states: dict[str, dict] = {}  # tool_use_id → {name, arguments_str}
        # SSE content_block index → tool_use_id 映射
        # （Anthropic 的 index 涵盖所有 content block，包括 text，
        #   不能直接用 list(tool_states.keys())[index] 取 tool）
        block_index_map: dict[int, str] = {}
        # 累积 usage
        accumulated_usage = Usage()

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST", self.url, json=body, headers=self.headers
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        msg = error_body.decode("utf-8", errors="replace")[:500]
                        if "prompt_too_long" in msg.lower() or (
                            response.status_code == 400
                            and "tool_use" in msg.lower()
                            and "token" in msg.lower()
                        ):
                            raise PromptTooLongError(
                                f"Anthropic 上下文超限: {msg[:200]}"
                            )
                        raise RuntimeError(
                            f"Anthropic API 返回错误 {response.status_code}: {msg}"
                        )

                    async for line in response.aiter_lines():
                        if not line or line.startswith(": "):
                            continue
                        if line.startswith("event:"):
                            continue
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            event_type = data.get("type", "")

                            # ── 消息开始：捕获 input/cache usage ──
                            if event_type == "message_start":
                                msg = data.get("message", {})
                                u = msg.get("usage", {})
                                accumulated_usage.input_tokens = u.get(
                                    "input_tokens", 0
                                )
                                accumulated_usage.cache_write_tokens = u.get(
                                    "cache_creation_input_tokens", 0
                                )
                                accumulated_usage.cache_read_tokens = u.get(
                                    "cache_read_input_tokens", 0
                                )

                            # ── 工具调用：content_block_start ──
                            elif event_type == "content_block_start":
                                block = data.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    tool_id = block.get("id", "")
                                    tool_name = block.get("name", "")
                                    tool_states[tool_id] = {
                                        "name": tool_name,
                                        "arguments_str": "",
                                    }
                                    # 记录 SSE index → tool_id 映射
                                    block_index_map[data.get("index", 0)] = tool_id
                                    yield StreamEvent(
                                        type="tool_start",
                                        tool_id=tool_id,
                                        tool_name=tool_name,
                                    )

                            # ── 内容增量 ──
                            elif event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                delta_type = delta.get("type", "")
                                if delta_type == "thinking_delta":
                                    thinking_text = delta.get("thinking", "")
                                    if thinking_text:
                                        yield StreamEvent(
                                            "thinking", thinking_text
                                        )
                                elif delta_type == "text_delta":
                                    text = delta.get("text", "")
                                    if text:
                                        yield StreamEvent("text", text)
                                elif delta_type == "input_json_delta":
                                    partial = delta.get("partial_json", "")
                                    index = data.get("index", 0)
                                    tid = block_index_map.get(index)
                                    if tid is not None and tid in tool_states:
                                        tool_states[tid][
                                            "arguments_str"
                                        ] += partial
                                        args_dict = _safe_json_parse(
                                            tool_states[tid]["arguments_str"]
                                        )
                                        yield StreamEvent(
                                            type="tool_delta",
                                            text=partial,
                                            tool_id=tid,
                                            tool_name=tool_states[tid][
                                                "name"
                                            ],
                                            tool_arguments_sofar=args_dict,
                                        )

                            # ── 内容块结束 ──
                            elif event_type == "content_block_stop":
                                index = data.get("index", 0)
                                tid = block_index_map.get(index)
                                if tid is not None and tid in tool_states:
                                    args_dict = _safe_json_parse(
                                        tool_states[tid]["arguments_str"]
                                    )
                                    yield StreamEvent(
                                        type="tool_end",
                                        tool_id=tid,
                                        tool_name=tool_states[tid]["name"],
                                        tool_arguments_sofar=args_dict,
                                    )

                            # ── 消息 delta：捕获 output_tokens ──
                            elif event_type == "message_delta":
                                u = data.get("usage", {})
                                accumulated_usage.output_tokens = u.get(
                                    "output_tokens", 0
                                )

                            # ── 消息结束 ──
                            elif event_type == "message_stop":
                                yield StreamEvent(
                                    "done", usage=accumulated_usage
                                )
                                return

        except httpx.HTTPError as e:
            raise RuntimeError(f"Anthropic API 网络请求失败: {e}") from e


# ── OpenAI 后端 ───────────────────────────────────────────────


class OpenAIProvider(BaseProvider):
    """OpenAI Chat Completions API SSE 流。

    端点: POST {base_url}/v1/chat/completions
    支持 function calling（工具调用），不支持 extended thinking。
    缓存策略：stable 放 system 消息前缀利用自动前缀缓存。
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        base = config.base_url.rstrip("/")
        self.url = f"{base}/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

    def build_body(self, request: Request) -> dict:
        """返回即将发送给 OpenAI API 的请求体 dict。"""
        api_messages: list[dict] = []
        system_content = request.system_stable
        if request.system_environment:
            if system_content:
                system_content += "\n\n" + request.system_environment
            else:
                system_content = request.system_environment
        if system_content:
            api_messages.append({"role": "system", "content": system_content})
        api_messages.extend(_format_messages_openai(request.messages))
        if request.reminder:
            api_messages.append({"role": "user", "content": request.reminder})

        body: dict = {
            "model": self.config.model,
            "messages": api_messages,
            "stream": True,
        }
        if request.tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.parameters,
                }}
                for t in request.tools
            ]
        return body

    async def stream(
        self,
        request: Request,
    ) -> AsyncGenerator[StreamEvent, None]:
        body = self.build_body(request)

        # 追踪工具调用累积状态
        tool_states: dict[int, dict] = {}  # index → {id, name, arguments_str}
        # 累积 usage
        accumulated_usage = Usage()

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST", self.url, json=body, headers=self.headers
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        msg = error_body.decode("utf-8", errors="replace")[:500]
                        if "context_length_exceeded" in msg.lower() or (
                            response.status_code == 400
                            and "token" in msg.lower()
                            and (
                                "maximum" in msg.lower()
                                or "exceed" in msg.lower()
                            )
                        ):
                            raise PromptTooLongError(
                                f"OpenAI 上下文超限: {msg[:200]}"
                            )
                        raise RuntimeError(
                            f"OpenAI API 返回错误 {response.status_code}: {msg}"
                        )

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            # 如有未收尾的工具调用，先 fire tool_end
                            if tool_states:
                                for idx, state in list(
                                    tool_states.items()
                                ):
                                    args_dict = _safe_json_parse(
                                        state["arguments_str"]
                                    )
                                    yield StreamEvent(
                                        type="tool_end",
                                        tool_id=state["id"],
                                        tool_name=state["name"],
                                        tool_arguments_sofar=args_dict,
                                    )
                                tool_states.clear()
                            yield StreamEvent("done", usage=accumulated_usage)
                            return
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # ── 捕获 usage（最后 chunk 携带）──
                        u = data.get("usage")
                        if u:
                            accumulated_usage.input_tokens = u.get(
                                "prompt_tokens", 0
                            )
                            accumulated_usage.output_tokens = u.get(
                                "completion_tokens", 0
                            )
                            # OpenAI prompt_tokens_details.cached_tokens
                            details = u.get("prompt_tokens_details", {})
                            accumulated_usage.cache_read_tokens = details.get(
                                "cached_tokens", 0
                            )

                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta", {})

                        # ── 普通文本增量 ──
                        content = delta.get("content", "")
                        if content:
                            yield StreamEvent("text", content)
                            continue

                        # ── 工具调用增量 ──
                        tool_calls = delta.get("tool_calls", [])
                        if tool_calls:
                            for tc in tool_calls:
                                idx = tc.get("index", 0)
                                if idx not in tool_states:
                                    tool_states[idx] = {
                                        "id": tc.get("id", ""),
                                        "name": "",
                                        "arguments_str": "",
                                    }

                                fn = tc.get("function", {})

                                # 工具名首次出现 → tool_start
                                fn_name = fn.get("name", "")
                                if fn_name:
                                    tool_states[idx]["name"] = fn_name
                                    yield StreamEvent(
                                        type="tool_start",
                                        tool_id=tool_states[idx]["id"],
                                        tool_name=fn_name,
                                    )

                                # 参数增量
                                fn_args = fn.get("arguments", "")
                                if fn_args:
                                    tool_states[idx][
                                        "arguments_str"
                                    ] += fn_args
                                    args_dict = _safe_json_parse(
                                        tool_states[idx]["arguments_str"]
                                    )
                                    yield StreamEvent(
                                        type="tool_delta",
                                        text=fn_args,
                                        tool_id=tool_states[idx]["id"],
                                        tool_name=tool_states[idx]["name"],
                                        tool_arguments_sofar=args_dict,
                                    )

                        # 检查 finish_reason
                        finish = choice.get("finish_reason", "")
                        if finish in ("tool_calls", "stop") and tool_states:
                            for idx, state in list(tool_states.items()):
                                args_dict = _safe_json_parse(
                                    state["arguments_str"]
                                )
                                yield StreamEvent(
                                    type="tool_end",
                                    tool_id=state["id"],
                                    tool_name=state["name"],
                                    tool_arguments_sofar=args_dict,
                                )
                            tool_states.clear()

        except httpx.HTTPError as e:
            raise RuntimeError(f"OpenAI API 网络请求失败: {e}") from e


# ── 消息格式化工具 ────────────────────────────────────────────


def _format_messages_anthropic(messages: list[Message]) -> list[dict]:
    """将内部 Message 列表转为 Anthropic API 格式。

    处理普通消息、带 tool_calls 的 assistant 消息和带 tool_result 的 user 消息。
    连续的 tool_result 消息合并为单条 user 消息（Anthropic 协议要求：
    一个 assistant 中的 N 个 tool_use 必须由下一条 user 中的 N 个 tool_result 对应）。
    """
    result: list[dict] = []
    for m in messages:
        if m.tool_calls:
            # 构建 assistant 消息 + tool_use 内容块
            content_blocks = []
            if m.content:
                content_blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            result.append({"role": "assistant", "content": content_blocks})

        elif m.tool_result:
            # 连续的 tool_result 合并到同一条 user 消息
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": m.tool_result["tool_use_id"],
                "content": m.tool_result["content"],
                "is_error": m.tool_result.get("is_error", False),
            }
            if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                # 前一条也是 tool_result user → 合并
                result[-1]["content"].append(tool_result_block)
            else:
                result.append({"role": "user", "content": [tool_result_block]})

        else:
            # 普通消息：content 包装为 content block 数组格式
            result.append(
                {
                    "role": m.role,
                    "content": [{"type": "text", "text": m.content}],
                }
            )

    return result


def _format_messages_openai(messages: list[Message]) -> list[dict]:
    """将内部 Message 列表转为 OpenAI API 格式。

    处理普通消息、带 tool_calls 的 assistant 消息和带 tool_result 的 user 消息。
    """
    result: list[dict] = []
    for m in messages:
        if m.tool_calls:
            # 构建 assistant 消息 + tool_calls 数组
            entry: dict = {"role": "assistant", "content": m.content or None}
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(
                            tc.arguments, ensure_ascii=False
                        ),
                    },
                }
                for tc in m.tool_calls
            ]
            result.append(entry)

        elif m.tool_result:
            # 构建 tool 角色消息
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_result["tool_use_id"],
                    "content": m.tool_result["content"],
                }
            )

        else:
            # 普通消息：OpenAI 使用纯字符串 content
            result.append({"role": m.role, "content": m.content})

    return result


# ── 通用工具函数 ──────────────────────────────────────────────


def _safe_json_parse(s: str) -> dict | None:
    """尝试解析 JSON 字符串，失败返回 None。"""
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None
