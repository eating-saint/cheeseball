"""恢复三段构建（F15-F18）。

压缩后恢复上下文的三段结构：
1. 文件快照——最近读取的文件内容（最多 5 个，有截断）
2. 工具列表——名称 + 描述 JSON（不含 parameters schema）
3. 边界提示——固定文案提醒模型不要脑补
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from mewcode.context.constants import ESTIMATE_CHARS_PER_TOKEN, FILE_SNAPSHOT_TOKEN_CAP
from mewcode.context.file_tracker import FileReadTracker
from mewcode.provider import ToolDefinition


# F18: 固定边界提示文案
BOUNDARY_MESSAGE = (
    "[系统提示] 以上是对话历史的压缩摘要。如果你需要之前讨论过的文件原文、"
    "错误信息原文、或用户的确切原话，请使用文件读取工具重新获取对应文件或上下文，"
    "不要根据摘要进行猜测或脑补。"
)


@dataclass
class RecoverySections:
    """压缩后恢复上下文的三段内容。

    Attributes:
        file_snapshots_text: 文件快照格式化文本。
        tool_list_text: 工具名 + 描述 JSON 字符串。
        boundary_message: 固定边界提示文案。
    """

    file_snapshots_text: str
    tool_list_text: str
    boundary_message: str


def _build_file_snapshots(file_tracker: FileReadTracker) -> str:
    """构建文件快照文本（F16）。

    取最近 5 个文件，每个截断到 ~FILE_SNAPSHOT_TOKEN_CAP × 3.5 字符。

    Args:
        file_tracker: 文件读取追踪器。

    Returns:
        格式化的文件快照文本。无文件时返回空字符串。
    """
    recent = file_tracker.get_recent()
    if not recent:
        return ""

    char_cap = int(FILE_SNAPSHOT_TOKEN_CAP * ESTIMATE_CHARS_PER_TOKEN)

    parts: list[str] = []
    for snap in recent:
        content_text = snap.content_bytes.decode("utf-8", errors="replace")
        if len(content_text) > char_cap:
            content_text = content_text[:char_cap] + "\n(content truncated)"

        parts.append(
            f"### 最近读取的文件: {snap.path}\n"
            f"读取时间: {snap.read_at}\n"
            f"```\n{content_text}\n```\n"
            "---"
        )

    return "\n".join(parts)


def build_recovery_sections(
    file_tracker: FileReadTracker,
    tools: list[ToolDefinition],
) -> RecoverySections:
    """构建压缩后的恢复三段内容（F15）。

    Args:
        file_tracker: 文件读取追踪器（最近 5 文件）。
        tools: 工具定义列表——⚠️ 必须与即将发给 provider 的 tools 是同一份列表引用（F17）。

    Returns:
        RecoverySections 包含三段字符串。
    """
    # 文件快照
    file_snapshots_text = _build_file_snapshots(file_tracker)

    # 工具列表（F17: 与请求 tools 同引用，仅序列化 name + description）
    tool_summaries = [{"name": t.name, "description": t.description} for t in tools]
    tool_list_text = json.dumps(tool_summaries, ensure_ascii=False)

    return RecoverySections(
        file_snapshots_text=file_snapshots_text,
        tool_list_text=tool_list_text,
        boundary_message=BOUNDARY_MESSAGE,
    )
