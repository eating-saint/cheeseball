"""JSONL 解析与会话恢复（ch09 F20-F21）."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from cheeseball.provider import Message, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class RecoveryResult:
    """JSONL 恢复结果。"""

    messages: list[Message] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    session_id: str = ""
    last_ts: float | None = None
    need_compact: bool = False

    @property
    def time_gap_hours(self) -> float | None:
        """距离现在的时差（小时）。None 表示无法判断。"""
        if self.last_ts is None:
            return None
        return (time.time() - self.last_ts) / 3600


def load_jsonl(
    jsonl_path: Path,
    context_window: int,
) -> RecoveryResult:
    """解析 JSONL，从最后一个 compact 标记之后加载。

    内部处理四类异常：
      a) 坏行 → skip + warning
      b) 孤立 tool_use → 截断 + warning
      c) token 超限 → 标记在 RecoveryResult（调用方处理压缩）
      d) 时间跨度提醒 → 不在本函数插入，由调用方根据 time_gap_hours 处理

    Args:
        jsonl_path: JSONL 文件路径。
        context_window: 上下文窗口大小（token 数）。

    Returns:
        RecoveryResult 包含恢复的 Message 列表。
    """
    result = RecoveryResult(
        session_id=jsonl_path.parent.name,
    )

    if not jsonl_path.is_file():
        return result

    # 逐行读取
    raw_lines: list[dict] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                raw_lines.append(obj)
            except json.JSONDecodeError:
                result.warnings.append(f"跳过坏行: {line[:80]}...")
                continue

    # 找最后一个 compact 标记
    start_idx = _find_last_compact(raw_lines)

    # 将 JSONL 行转为 Message 对象
    messages: list[Message] = []
    for obj in raw_lines[start_idx:]:
        if obj.get("type") == "compact":
            continue  # compact 行本身不转为消息
        if obj.get("type") != "message":
            continue

        msg = _line_to_message(obj)
        if msg is not None:
            messages.append(msg)
            ts = obj.get("ts")
            if ts is not None:
                result.last_ts = ts

    # 检查孤立 tool_use（F21b）
    messages, orphan_warning = _check_orphan_tool_use(messages)
    if orphan_warning:
        result.warnings.append(orphan_warning)

    result.messages = messages

    # Token 超限检测（F21c）
    if messages and context_window > 0:
        estimated = _rough_token_estimate(messages)
        if estimated > context_window * 0.8:
            result.need_compact = True

    return result


def _find_last_compact(lines: list[dict]) -> int:
    """找到最后一个 type=="compact" 的行号 + 1，无则返回 0。"""
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].get("type") == "compact":
            return i + 1
    return 0


def _line_to_message(obj: dict) -> Message | None:
    """将 JSONL 一行转为 Message 对象。"""
    role = obj.get("role", "")
    content = obj.get("content", "")

    if role == "user":
        return Message(role="user", content=content)

    elif role == "assistant":
        tool_calls = None
        raw_tcs = obj.get("tool_calls")
        if raw_tcs:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=tc.get("input", {}),
                )
                for tc in raw_tcs
            ]
        return Message(role="assistant", content=content, tool_calls=tool_calls)

    elif role == "tool":
        tool_use_id = obj.get("tool_use_id", "")
        return Message(
            role="user",
            content="",
            tool_result={
                "tool_use_id": tool_use_id,
                "content": content,
                "is_error": False,
            },
        )

    return None


def _check_orphan_tool_use(messages: list[Message]) -> tuple[list[Message], str]:
    """检查末尾是否有孤立 tool_use（有 tool_use 无对应 tool_result）。

    从末尾向前扫描：如果最后一条有 tool_calls 的 assistant 消息之后
    没有足够的 tool_result 消息配对，则截断到该 assistant 消息之前。

    Returns:
        (截断后的消息列表, 警告文本或空字符串)
    """
    # 从末尾找到最后一个有 tool_calls 的 assistant
    last_assistant_with_tc_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.role == "assistant" and msg.tool_calls:
            last_assistant_with_tc_idx = i
            break

    if last_assistant_with_tc_idx < 0:
        return messages, ""

    # 计算该 assistant 消息有多少个 tool_use_id
    tc_ids: set[str] = set()
    for tc in messages[last_assistant_with_tc_idx].tool_calls or []:
        tc_ids.add(tc.id)

    # 统计之后有多少匹配的 tool_result
    matched = 0
    for j in range(last_assistant_with_tc_idx + 1, len(messages)):
        msg = messages[j]
        if msg.role == "user" and msg.tool_result:
            tid = msg.tool_result.get("tool_use_id", "")
            if tid in tc_ids:
                matched += 1

    if matched < len(tc_ids):
        # 不完整，截断
        return (
            messages[:last_assistant_with_tc_idx],
            f"截断孤立 tool_use: assistant index {last_assistant_with_tc_idx}, "
            f"期望 {len(tc_ids)} 个 tool_result，实际 {matched} 个",
        )

    return messages, ""


def _rough_token_estimate(messages: list[Message]) -> int:
    """粗略估算 token 数：总字符数 / 3.5。"""
    total_chars = 0
    for msg in messages:
        total_chars += len(msg.content or "")
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total_chars += len(tc.name) + len(json.dumps(tc.arguments, ensure_ascii=False))
        if msg.tool_result:
            total_chars += len(msg.tool_result.get("content", ""))
    return int(total_chars / 3.5)
