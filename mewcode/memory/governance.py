"""后台记忆治理——空闲时合并/删除/整理笔记（ch09 F33）."""

from __future__ import annotations

import json
import logging
import time

from mewcode.memory.manager import MAX_INDEX_LINES, MemoryManager, MemoryNote
from mewcode.provider import BaseProvider, Message, Request

logger = logging.getLogger(__name__)


class MemoryGovernance:
    """后台记忆治理——空闲时使用主 provider 发起独立 LLM 请求。

    在 asyncio.Task 中执行。

    用法::

        gov = MemoryGovernance(manager, provider)
        gov.reset_idle_timer()
        # ... 用户交互 ...
        executed = await gov.run_if_idle(idle_seconds=300)
    """

    def __init__(self, manager: MemoryManager, provider: BaseProvider) -> None:
        self._manager = manager
        self._provider = provider
        self._last_interaction = time.monotonic()

    def reset_idle_timer(self) -> None:
        """重置空闲计时器（每次用户交互后调用）。"""
        self._last_interaction = time.monotonic()

    async def run_if_idle(self, idle_seconds: float = 300) -> bool:
        """如果距上次用户交互 ≥ idle_seconds，执行一次治理。

        回顾所有笔记 → LLM 判断合并/删除/修正 → 原子替换。
        返回 True 表示已执行。

        Args:
            idle_seconds: 空闲秒数阈值。

        Returns:
            True 表示已执行治理，False 表示空闲不足。
        """
        elapsed = time.monotonic() - self._last_interaction
        if elapsed < idle_seconds:
            return False

        try:
            project_notes, user_notes = self._manager.get_all_notes()
            all_notes = project_notes + user_notes

            if not all_notes:
                return False

            # 构造 prompt
            notes_text = _format_all_notes(all_notes)
            prompt = (
                "## 当前所有记忆笔记\n\n"
                f"{notes_text}\n\n"
                "## 指令\n\n"
                "回顾以上所有笔记，进行以下整理：\n"
                "1. 合并重复或高度相似的笔记\n"
                "2. 删除过时或明显错误的笔记\n"
                "3. 修正前后矛盾的笔记\n"
                "4. 优化描述使其更清晰准确\n\n"
                "输出 JSON 格式：\n"
                "```json\n"
                "{\n"
                '  "keep": ["note_name_1", "note_name_2"],\n'
                '  "delete": ["obsolete_note_name"],\n'
                '  "modify": [{"name":"existing_name","description":"新描述","type":"project","content":"新正文"}]\n'
                "}\n"
                "```\n\n"
                "规则：\n"
                "- keep 列出应保留的笔记 name\n"
                "- delete 列出应删除的笔记 name\n"
                "- modify 列出需要修改的笔记（含新内容）\n"
                "- 未出现在 keep/delete 中的笔记默认保留\n"
                f"- 最终保留的笔记数不超过 {MAX_INDEX_LINES}\n"
            )

            request = Request(
                messages=[Message(role="user", content=prompt)],
                system_stable="你是一个记忆整理助手。负责合并、清理和优化用户的长期记忆笔记。",
            )

            full_text = ""
            async for ev in self._provider.stream(request):
                if ev.type == "text":
                    full_text += ev.text

            # 解析响应
            parsed = _parse_governance_json(full_text)
            if parsed is None:
                return False

            # 执行删除
            for name in parsed.get("delete", []):
                if not name:
                    continue
                # 从现有笔记中查找完整文件名
                for note in all_notes:
                    if note.name == name:
                        filename = f"{note.type}_{note.name}.md"
                        level = "user" if note.type in ("user", "feedback") else "project"
                        self._manager.delete_note(filename, level)
                        break

            # 执行修改
            for item in parsed.get("modify", []):
                name = item.get("name", "")
                if not name:
                    continue
                note_type = item.get("type", "project")
                level = "user" if note_type in ("user", "feedback") else "project"
                note = MemoryNote(
                    name=name,
                    description=item.get("description", ""),
                    type=note_type,
                    content=item.get("content", ""),
                )
                self._manager.write_note(note, level)

            # 重建两级索引
            p_notes, u_notes = self._manager.get_all_notes()
            self._manager.rebuild_index(p_notes, "project")
            self._manager.rebuild_index(u_notes, "user")

            logger.info("记忆治理完成")
            return True

        except Exception:
            logger.warning("记忆治理失败", exc_info=True)
            return False


def _format_all_notes(notes: list[MemoryNote]) -> str:
    """格式化所有笔记为 prompt 文本。"""
    lines: list[str] = []
    for n in notes:
        lines.append(f"### [{n.type}] {n.name}")
        lines.append(f"描述: {n.description}")
        lines.append(f"内容: {n.content[:300]}")
        lines.append("")
    return "\n".join(lines)


def _parse_governance_json(text: str) -> dict | None:
    """从 LLM 响应中提取治理 JSON。"""
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

    text = text.strip()
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("记忆治理 JSON 解析失败: %s", text[:200])
        return None
