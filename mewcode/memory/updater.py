"""异步记忆更新——使用主 provider 发起独立 LLM 请求（ch09 F25-F27）."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from mewcode.memory.manager import MemoryManager, MemoryNote
from mewcode.provider import BaseProvider, Message, Request

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    """一次记忆更新的结果。"""

    added: list[MemoryNote] = field(default_factory=list)
    modified: list[MemoryNote] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)  # 文件名列表


class MemoryUpdater:
    """异步记忆更新——使用主 provider 发起独立 LLM 请求。

    在 asyncio.Task 中执行，不阻塞主循环。

    用法::

        updater = MemoryUpdater(manager, provider)
        result = await updater.update(conversation_snapshot)
    """

    def __init__(self, manager: MemoryManager, provider: BaseProvider) -> None:
        self._manager = manager
        self._provider = provider

    async def update(
        self,
        conversation_snapshot: list[Message],
    ) -> UpdateResult:
        """根据对话快照更新记忆。

        1. 读取现有笔记 + MEMORY.md 摘要
        2. 构造 prompt：让 LLM 根据对话快照判断增/改/删
        3. 解析 LLM 响应，执行文件操作
        4. 重建 MEMORY.md 索引
        5. 失败时静默返回空 UpdateResult

        Args:
            conversation_snapshot: 对话消息的不可变副本。

        Returns:
            UpdateResult 包含新增/修改/删除的笔记。
        """
        try:
            # 读取现有状态
            project_notes, user_notes = self._manager.get_all_notes()
            all_notes = project_notes + user_notes
            existing_index = self._manager.load_index()

            # 构造 snapshot 摘要
            snapshot_text = _format_snapshot(conversation_snapshot)

            # 构造 prompt
            prompt = _build_update_prompt(existing_index, all_notes, snapshot_text)

            # 调 LLM
            request = Request(
                messages=[Message(role="user", content=prompt)],
                system_stable="你是一个记忆管理助手。根据对话内容提取值得长期记住的信息。",
            )

            full_text = ""
            async for ev in self._provider.stream(request):
                if ev.type == "text":
                    full_text += ev.text

            # 解析响应
            parsed = _parse_llm_json(full_text)
            if parsed is None:
                return UpdateResult()

            # 执行文件操作
            result = UpdateResult()

            for item in parsed.get("added", []):
                note = MemoryNote(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    type=item.get("type", "project"),
                    content=item.get("content", ""),
                )
                if not note.name or not note.description:
                    continue

                # 判断级别
                level = "user" if note.type in ("user", "feedback") else "project"
                self._manager.write_note(note, level)
                result.added.append(note)

            for item in parsed.get("modified", []):
                name = item.get("name", "")
                if not name:
                    continue
                # 查找现有笔记并更新
                note_type = item.get("type", "project")
                level = "user" if note_type in ("user", "feedback") else "project"
                note = MemoryNote(
                    name=name,
                    description=item.get("description", ""),
                    type=note_type,
                    content=item.get("content", ""),
                )
                self._manager.write_note(note, level)
                result.modified.append(note)

            for filename in parsed.get("deleted", []):
                if not filename:
                    continue
                # 尝试两级删除
                self._manager.delete_note(filename, "project")
                self._manager.delete_note(filename, "user")
                result.deleted.append(filename)

            # 重建索引
            if result.added or result.modified or result.deleted:
                p_notes, u_notes = self._manager.get_all_notes()
                self._manager.rebuild_index(p_notes, "project")
                self._manager.rebuild_index(u_notes, "user")

                logger.info(
                    "记忆更新完成: +%d ~%d -%d",
                    len(result.added),
                    len(result.modified),
                    len(result.deleted),
                )

            return result

        except Exception:
            logger.warning("记忆更新失败", exc_info=True)
            return UpdateResult()


def _format_snapshot(messages: list[Message]) -> str:
    """将消息列表格式化为可读文本。"""
    lines: list[str] = []
    for msg in messages[-20:]:  # 最近 20 条
        role = msg.role
        content = msg.content or ""
        if msg.tool_result:
            content = f"[工具结果: {msg.tool_result.get('tool_use_id', '')}] {msg.tool_result.get('content', '')[:200]}"
        if msg.tool_calls:
            tc_names = [tc.name for tc in msg.tool_calls]
            content = f"[调用工具: {', '.join(tc_names)}] {content}"
        lines.append(f"[{role}] {content[:500]}")
    return "\n".join(lines)


def _build_update_prompt(
    existing_index: str,
    all_notes: list[MemoryNote],
    snapshot_text: str,
) -> str:
    """构造记忆更新 prompt。"""
    notes_summary = "\n".join(
        f"- [{n.type}] {n.name}: {n.description}"
        for n in all_notes
    )
    if not notes_summary:
        notes_summary = "(无现有笔记)"

    return (
        "## 现有记忆索引\n\n"
        f"{existing_index or '(空)'}\n\n"
        "## 现有笔记摘要\n\n"
        f"{notes_summary}\n\n"
        "## 最近对话\n\n"
        f"{snapshot_text}\n\n"
        "## 指令\n\n"
        "根据以上对话内容，判断哪些信息值得长期记住。输出 JSON 格式：\n"
        "```json\n"
        "{\n"
        '  "added": [{"name":"short_slug","description":"一行摘要","type":"project|user|feedback|reference","content":"正文"}],\n'
        '  "modified": [{"name":"existing_slug","description":"更新后摘要","type":"...","content":"更新后正文"}],\n'
        '  "deleted": ["filename_to_delete.md"]\n'
        "}\n"
        "```\n\n"
        "规则：\n"
        "- 只记录长期有价值的信息（用户偏好、项目规范、重要决策等）\n"
        "- 不要记录一次性/临时信息\n"
        "- 如果无需更新，返回空的 added/modified/deleted 数组\n"
        "- name 使用小写下划线格式\n"
        "- 索引不超过 200 行 / 25KB\n"
    )


def _parse_llm_json(text: str) -> dict | None:
    """从 LLM 响应中提取 JSON。"""
    # 尝试提取 ```json ... ``` 块
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end]
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            text = text[start:end]

    # 尝试找 JSON 对象
    text = text.strip()
    # 找到第一个 { 和最后一个 }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM 记忆更新响应 JSON 解析失败: %s", text[:200])
        return None
