"""第 2 层摘要核心：prompt 构建、请求发送、响应解析、PTL 重试、近期原文选择（F7-F12, F27）。

摘要流程：
1. 构建 9 部分摘要 prompt（两阶段：<analysis> → <summary>）
2. 构造不带 tools 的摘要请求
3. 发送 → 成功则解析 <summary> 内容
4. 若 PromptTooLongError → 丢弃消息组重试
5. 选择近期原文 + 构建恢复段 → 返回 CompactResult
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cheeseball.context.constants import (
    ESTIMATE_CHARS_PER_TOKEN,
    PTL_DIRECT_RETRY_MAX,
    PTL_RATIO_DROP_STEP,
    RECENT_COUNT_FLOOR,
    RECENT_TOKEN_FLOOR,
)
from cheeseball.context.estimator import TokenEstimator
from cheeseball.context.file_tracker import FileReadTracker
from cheeseball.context.message_grouper import (
    drop_groups,
    drop_ratio_groups,
    flatten_groups,
    group_messages,
)
from cheeseball.context.recovery import build_recovery_sections
from cheeseball.provider import (
    BaseProvider,
    Message,
    PromptTooLongError,
    Request,
    ToolDefinition,
    Usage,
)


@dataclass
class CompactResult:
    """compaction 结果。

    Attributes:
        before_tokens: 摘要前估算 token 数。
        after_tokens: 摘要后估算 token 数。
        summary_text: 提取的摘要文本（不含 analysis）。
        groups_dropped: PTL 重试时丢弃的组数。
        ptl_retries: PTL 重试次数。
    """

    before_tokens: int
    after_tokens: int
    summary_text: str
    groups_dropped: int = 0
    ptl_retries: int = 0


class CompactError(Exception):
    """摘要失败异常。

    Attributes:
        message: 错误描述。
        ptl_exhausted: PTL 重试耗尽时为 True。
    """

    def __init__(self, message: str, ptl_exhausted: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.ptl_exhausted = ptl_exhausted


# ── 摘要 Prompt 模板 ──────────────────────────────────────────

_SUMMARY_SYSTEM_PROMPT = """你是一个对话摘要助手。你的任务是将一段对话历史压缩为结构化的摘要。

## 要求

1. 先输出 `<analysis>` 标签，在其中分析对话的关键信息点。这是你的工作草稿，列出你对各部分的初步判断。
2. 然后输出 `<summary>` 标签，在其中写出正式的、精炼的摘要。
3. **不要调用任何工具**——这是纯文本摘要任务。
4. 摘要应足够详细，使得阅读者无需查阅原文就能继续工作。

## 摘要应包含以下 9 个部分：

① **主要请求和意图** — 用户想要完成什么？
② **关键技术概念** — 涉及哪些技术栈、框架、API？
③ **文件和代码段** — 讨论了哪些文件？做了哪些修改？
④ **错误和修复** — 遇到了哪些错误？如何解决的？
⑤ **问题解决过程** — 排查问题的思路和步骤
⑥ **所有用户消息原文优先逐条保留** — 用户的确切原话，尽可能保留
⑦ **待办任务** — 还有什么未完成的工作？
⑧ **当前工作**（最详细）— 最近在做什么？当前状态是什么？
⑨ **可能的下一步** — 接下来可能要做什么？
"""


def build_summary_prompt(messages_text: str) -> str:
    """构建摘要请求的 user prompt（F10）。

    Args:
        messages_text: 序列化后的对话历史文本。

    Returns:
        完整的 user prompt 字符串。
    """
    return f"请对以下对话历史进行结构化摘要：\n\n{messages_text}"


def build_summary_request(
    messages: list[Message],
    system_stable: str,
    system_environment: str,
) -> Request:
    """构造不携带 tools 的摘要请求（F8）。

    Args:
        messages: 待摘要的消息列表。
        system_stable: 复用主对话的稳定系统提示。
        system_environment: 复用主对话的环境信息。

    Returns:
        Request 对象，tools 为空列表。
    """
    # 序列化消息为文本
    lines: list[str] = []
    for m in messages:
        role = m.role
        content = m.content
        if m.tool_calls:
            tool_names = [tc.name for tc in m.tool_calls]
            content += f"\n[调用工具: {', '.join(tool_names)}]"
        if m.tool_result:
            tid = m.tool_result.get("tool_use_id", "")
            tr_content = m.tool_result.get("content", "")
            is_preview = tr_content.startswith("[工具结果已存盘:")
            if is_preview:
                lines.append(f"{role}: [工具结果已存盘]")
            else:
                tr_preview = tr_content[:200] + "..." if len(tr_content) > 200 else tr_content
                lines.append(f"{role}: [tool_result {tid}] {tr_preview}")
            continue
        lines.append(f"{role}: {content}")

    messages_text = "\n".join(lines)
    user_prompt = build_summary_prompt(messages_text)

    # 构造摘要专用的系统提示：摘要 helper prompt + 原系统提示
    full_system_stable = _SUMMARY_SYSTEM_PROMPT
    if system_stable:
        full_system_stable += "\n\n## 原始系统提示（供参考）\n" + system_stable

    return Request(
        messages=[Message(role="user", content=user_prompt)],
        tools=[],  # F8: 不携带工具
        system_stable=full_system_stable,
        system_environment=system_environment,
    )


def parse_summary_response(text: str) -> str | None:
    """提取 <summary>...</summary> 内容，丢弃 <analysis>（F9）。

    Args:
        text: LLM 返回的完整文本。

    Returns:
        摘要正文，或 None（提取失败）。
    """
    match = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def select_recent_messages(
    messages: list[Message],
    estimator: TokenEstimator,
) -> list[Message]:
    """从尾部倒序选择近期原文消息（F11-F12）。

    同时满足两个下界才停止：
    - 累计 token ≥ RECENT_TOKEN_FLOOR (10000)
    - 累计条数 ≥ RECENT_COUNT_FLOOR (5)
    截断点检查（F12）：不切断 tool_use/tool_result 对。

    Args:
        messages: 完整消息列表。
        estimator: 用于估算每条消息 token 的估算器。

    Returns:
        尾部保留的近期原文消息列表。
    """
    if not messages:
        return []

    recent: list[Message] = []
    cumulative_tokens = 0

    for m in reversed(messages):
        # 估算该消息的 token 数
        content = m.content or ""
        msg_tokens = max(1, int(len(content) / ESTIMATE_CHARS_PER_TOKEN))
        cumulative_tokens += msg_tokens
        recent.append(m)

        # 两个下界都满足才停
        if cumulative_tokens >= RECENT_TOKEN_FLOOR and len(recent) >= RECENT_COUNT_FLOOR:
            break

    # 反转回顺序
    recent.reverse()

    # F12: 检查第一条消息是否是落单 tool_result
    if recent and recent[0].tool_result is not None:
        # 向前推进到原始位置的前一条（含 tool_calls 的 assistant 消息）
        first_idx = messages.index(recent[0]) if recent[0] in messages else -1
        if first_idx > 0:
            prev_msg = messages[first_idx - 1]
            if prev_msg.tool_calls:
                recent.insert(0, prev_msg)

    return recent


async def execute_compact(
    provider: BaseProvider,
    messages: list[Message],
    tools: list[ToolDefinition],
    system_stable: str,
    system_environment: str,
    file_tracker: FileReadTracker,
    estimator: TokenEstimator,
    trigger: str,
) -> CompactResult:
    """执行完整摘要流程（F7, F27）。

    1. 构建摘要请求
    2. 发送 → PTL 时按组丢弃重试
    3. 解析响应
    4. 选择近期原文 + 构建恢复段

    Args:
        provider: LLM provider。
        messages: 当前消息列表（已过第 1 层处理）。
        tools: 工具定义列表（必须与请求 tools 同引用，F17）。
        system_stable: 稳定系统提示。
        system_environment: 环境信息。
        file_tracker: 文件读取追踪器。
        estimator: token 估算器。
        trigger: 触发类型（"auto"/"manual"/"emergency"）。

    Returns:
        CompactResult 包含摘要前后 token 对比。

    Raises:
        CompactError: 摘要失败（含 PTL 耗尽）。
    """
    before_estimate = estimator.estimate()
    before_tokens = before_estimate.total if before_estimate else 0

    # 分组（用于 PTL 重试时丢弃）
    groups = group_messages(messages)
    direct_retries = 0
    total_dropped = 0
    summary_text: str | None = None
    ptl_retries = 0

    current_messages = list(messages)

    while True:
        req = build_summary_request(
            current_messages, system_stable, system_environment
        )

        try:
            # 流式收集摘要响应
            full_text = ""
            async for ev in provider.stream(req):
                if ev.type == "text":
                    full_text += ev.text
                elif ev.type == "done":
                    break

            # 解析摘要
            summary_text = parse_summary_response(full_text)
            if summary_text is None:
                raise CompactError(
                    f"摘要响应解析失败：未找到 <summary> 标签", ptl_exhausted=False
                )
            break  # 成功

        except PromptTooLongError:
            ptl_retries += 1
            if not groups:
                raise CompactError(
                    "PTL 重试耗尽：所有消息组已丢弃", ptl_exhausted=True
                )

            if direct_retries < PTL_DIRECT_RETRY_MAX:
                groups = drop_groups(groups, 1)
                direct_retries += 1
                total_dropped += 1
            else:
                if not groups:
                    raise CompactError(
                        "PTL 重试耗尽：没有更多组可丢弃", ptl_exhausted=True
                    )
                groups, n = drop_ratio_groups(groups, PTL_RATIO_DROP_STEP)
                total_dropped += n

            if not groups:
                raise CompactError(
                    "PTL 重试耗尽：所有消息组已丢弃", ptl_exhausted=True
                )

            current_messages = flatten_groups(groups)

    # 选择近期原文
    recent = select_recent_messages(messages, estimator)

    # 构建恢复段（F17: tools 与请求同一引用）
    recovery = build_recovery_sections(file_tracker, tools)

    # 估算摘要后 token
    summary_estimate = int(len(summary_text) / ESTIMATE_CHARS_PER_TOKEN)
    recovery_estimate = int(
        (len(recovery.file_snapshots_text) +
         len(recovery.tool_list_text) +
         len(recovery.boundary_message)) / ESTIMATE_CHARS_PER_TOKEN
    )
    recent_estimate = sum(
        max(1, int(len(m.content or "") / ESTIMATE_CHARS_PER_TOKEN))
        for m in recent
    )
    after_tokens = summary_estimate + recovery_estimate + recent_estimate

    return CompactResult(
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        summary_text=summary_text,
        groups_dropped=total_dropped,
        ptl_retries=ptl_retries,
    )
