"""消息分组器：按 user→assistant/tool 往返分组（F27）。

每组以用户提交（role=="user" 且不含 tool_result）起始，
后续 assistant/tool_result 消息归入同组。
PTL 重试时按组丢弃，保证不切断 tool_use/tool_result 对。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cheeseball.provider import Message


@dataclass
class MessageGroup:
    """一组连续的对话消息（一个 user→responses 往返）。

    Attributes:
        messages: 该组包含的消息列表。
        start_index: 该组在原消息列表中的起始位置。
    """

    messages: list[Message]
    start_index: int


def group_messages(messages: list[Message]) -> list[MessageGroup]:
    """将消息列表分组，每组以用户提交（非 tool_result）起始。

    Args:
        messages: 对话消息列表。

    Returns:
        MessageGroup 列表，空列表返回 []。
    """
    if not messages:
        return []

    groups: list[MessageGroup] = []
    current_group: list[Message] = []
    start_index = 0

    for i, msg in enumerate(messages):
        # 判断是否为"用户提交"（role==user 且不含 tool_result）
        is_user_submission = (
            msg.role == "user" and msg.tool_result is None
        )

        if is_user_submission and current_group:
            # 遇到新的用户提交 → 关闭当前组
            groups.append(
                MessageGroup(messages=current_group, start_index=start_index)
            )
            current_group = []
            start_index = i

        current_group.append(msg)

    # 最后一组
    if current_group:
        groups.append(
            MessageGroup(messages=current_group, start_index=start_index)
        )

    return groups


def drop_groups(
    groups: list[MessageGroup], count: int
) -> list[MessageGroup]:
    """丢弃前 count 组。

    Args:
        groups: 分组列表。
        count: 要丢弃的组数。

    Returns:
        剩余组列表。
    """
    if count >= len(groups):
        return []
    return groups[count:]


def drop_ratio_groups(
    groups: list[MessageGroup], ratio: float
) -> tuple[list[MessageGroup], int]:
    """按比例丢弃最旧组。

    Args:
        groups: 剩余分组列表。
        ratio: 丢弃比例（如 0.2 表示丢弃 20%）。

    Returns:
        (剩余组列表, 丢弃数量)。
    """
    n = max(1, math.ceil(len(groups) * ratio))
    dropped = min(n, len(groups))
    return groups[dropped:], dropped


def flatten_groups(groups: list[MessageGroup]) -> list[Message]:
    """将所有组展平为单层消息列表。

    Args:
        groups: 分组列表。

    Returns:
        展平后的消息列表。
    """
    result: list[Message] = []
    for g in groups:
        result.extend(g.messages)
    return result
