"""第 1 层压缩：工具结果落盘 + 预览体替换（F1-F6, N1, N6）。

纯字符串同步处理，不调 LLM。每次 API 请求前毫秒级完成。
返回修改后的消息列表 + OffloadResult 统计。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mewcode.context.constants import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTE_CAP,
    PREVIEW_HEAD_LINE_CAP,
    SINGLE_RESULT_THRESHOLD,
    TOOL_RESULTS_SUBDIR,
)
from mewcode.context.ledger import ReplacementLedger
from mewcode.provider import Message


@dataclass
class OffloadResult:
    """第 1 层压缩结果统计。

    Attributes:
        checked: 本轮检查的 tool_result 数量。
        replaced: 本次新替换的数量。
        skipped: 已有替换决策、幂等跳过的数量。
        kept: 决策保留原文的数量。
        total_bytes_written: 本轮落盘字节总数。
    """

    checked: int = 0
    replaced: int = 0
    skipped: int = 0
    kept: int = 0
    total_bytes_written: int = 0


def _build_preview(
    tool_use_id: str,
    content: str,
    byte_count: int,
    file_path: str,
) -> str:
    """构建工具结果预览字符串（F3）。纯函数：相同输入产生逐字节相同的输出。"""
    lines = content.split("\n")
    head_lines = lines[:PREVIEW_HEAD_LINE_CAP]
    head = "\n".join(head_lines)
    head_bytes = head.encode("utf-8")
    if len(head_bytes) > PREVIEW_HEAD_BYTE_CAP:
        head = head_bytes[:PREVIEW_HEAD_BYTE_CAP].decode("utf-8", errors="replace")

    return (
        f"[工具结果已存盘: {byte_count} 字节]\n"
        f"{head}\n"
        f"[存储路径: {file_path}]\n"
        f"[如需完整内容，请使用 read_file 读取上述路径]"
    )


def _write_tool_result(
    session_dir: Path,
    tool_use_id: str,
    content: str,
) -> bool:
    """将工具结果落盘。幂等：文件已存在跳过写入。"""
    target_path = session_dir / TOOL_RESULTS_SUBDIR / tool_use_id
    if target_path.exists():
        return True
    try:
        os.makedirs(target_path.parent, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def offload_and_snip(
    messages: list[Message],
    ledger: ReplacementLedger,
    session_dir: Path,
    protected_from: int | None = None,
) -> OffloadResult:
    """对消息列表原地执行第 1 层预防性压缩（F1-F6）。

    直接修改传入的 messages（原地替换 tool_result content 为预览体）。
    与 plan.md 技术决策一致：原地修改 conv._messages，保证同一份
    string 对象跨轮次复用，保护 Anthropic prompt cache 命中率。

    两阶段扫描（F2a）：
    阶段 1: 收集所有 tool_result，按字节倒序 → F1 检查（>50KB 落盘）
    阶段 2: F2 聚合检查（剩余总字节 > 200KB → 从大往小落盘直到达标）

    决策冻结：本轮已评估 id 不重复判定。幂等：已 seen id 复用账本决策。

    Returns:
        OffloadResult 统计信息。
    """
    result = OffloadResult()
    evaluated_in_this_call: set[str] = set()

    # ── 阶段 1: 收集 tool_result 条目 ──
    # (msg_index, tool_use_id, content, content_bytes)
    entries: list[tuple[int, str, str, int]] = []
    for i, msg in enumerate(messages):
        if msg.tool_result is None:
            continue
        tid = msg.tool_result.get("tool_use_id", "")
        content = msg.tool_result.get("content", "")
        if not tid or not content:
            continue
        entries.append((i, tid, content, len(content.encode("utf-8"))))

    if not entries:
        return result

    result.checked = len(entries)

    # 按字节倒序排列（F2a）
    entries.sort(key=lambda e: e[3], reverse=True)
    # tid → msg_index 映射用于后续写回
    tid_to_entry: dict[str, tuple[int, str, int]] = {}
    for idx, tid, content, cb in entries:
        tid_to_entry[tid] = (idx, content, cb)

    # ── 阶段 2a: F1 单条检查 ──
    # 账本已有的 → 复用决策
    # 未决策 + 超 SINGLE_RESULT_THRESHOLD → 落盘+替换
    replaced_tids: set[str] = set()
    for idx, tid, content, cb in entries:
        evaluated_in_this_call.add(tid)

        if ledger.is_seen(tid):
            replacement = ledger.get_replacement(tid)
            if replacement is not None:
                messages[idx].tool_result["content"] = replacement
                replaced_tids.add(tid)
            result.skipped += 1
            continue

        if cb > SINGLE_RESULT_THRESHOLD:
            target_path = session_dir / TOOL_RESULTS_SUBDIR / tid
            if _write_tool_result(session_dir, tid, content):
                preview = _build_preview(tid, content, cb, str(target_path))
                ledger.commit_replace(tid, preview)
                messages[idx].tool_result["content"] = preview
                replaced_tids.add(tid)
                result.replaced += 1
                result.total_bytes_written += cb
            else:
                result.kept += 1
        else:
            result.kept += 1

    # ── 阶段 2b: F2 聚合检查 ──
    # 计算未被替换的 tool_result 总字节数
    remaining: list[tuple[int, str, int]] = []  # (msg_index, tid, content_bytes)
    remaining_total = 0
    for idx, tid, content, cb in entries:
        if tid not in replaced_tids and not ledger.is_seen(tid):
            remaining.append((idx, tid, cb))
            remaining_total += cb
        elif tid in replaced_tids:
            # 预览字符串的字节数
            preview_bytes = len(messages[idx].tool_result["content"].encode("utf-8"))
            remaining_total += preview_bytes

    # 如果剩余聚合超过限额，从大往小落盘直到达标
    if remaining_total > MESSAGE_AGGREGATE_LIMIT:
        # remaining 已按字节倒序（因为 entries 已排序），但还是重新排一下
        remaining.sort(key=lambda e: e[2], reverse=True)
        budget = MESSAGE_AGGREGATE_LIMIT

        for idx, tid, cb in remaining:
            if remaining_total <= budget:
                break
            # 落盘此项
            content = messages[idx].tool_result["content"]
            # 检查是否已经是预览体（被 F1 替换）
            if content.startswith("[工具结果已存盘:"):
                remaining_total -= cb
                continue

            target_path = session_dir / TOOL_RESULTS_SUBDIR / tid
            if _write_tool_result(session_dir, tid, content):
                preview = _build_preview(tid, content, cb, str(target_path))
                ledger.commit_replace(tid, preview)
                messages[idx].tool_result["content"] = preview
                result.replaced += 1
                result.total_bytes_written += cb
                result.kept -= 1
                remaining_total -= (cb - len(preview.encode("utf-8")))

    return result
