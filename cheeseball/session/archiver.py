"""JSONL 会话存档追加写入器（ch09 F11-F14）."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SessionArchiver:
    """JSONL 追加写入器。Conversation 在各修改点显式调用其方法。

    用法::

        archiver = SessionArchiver(Path("session/conversation.jsonl"))
        archiver.append_message("user", "你好")
        archiver.append_message("assistant", "你好！", model="claude-sonnet-5")
        archiver.append_compact_and_rebuild([msg1, msg2])
    """

    def __init__(self, jsonl_path: Path) -> None:
        self._path = jsonl_path
        self._index = 0
        self._lock = threading.Lock()
        self._last_role: str = ""  # 最后一次写入的 role

    @property
    def path(self) -> Path:
        """返回 JSONL 文件路径。"""
        return self._path

    @property
    def index(self) -> int:
        """返回当前消息序号。"""
        return self._index

    @index.setter
    def index(self, value: int) -> None:
        """设置当前消息序号（恢复会话时使用）。"""
        self._index = value

    @property
    def last_role(self) -> str:
        """返回最后一次写入的 role。"""
        return self._last_role

    def append_message(
        self,
        role: str,
        content: str,
        model: str | None = None,
        tool_calls: list[dict] | None = None,
        tool_use_id: str | None = None,
    ) -> None:
        """追加一行 JSONL 消息。

        Args:
            role: "user" | "assistant" | "tool"
            content: 完整文本内容
            model: 仅 assistant 时
            tool_calls: 仅 assistant 有工具调用时
            tool_use_id: 仅 tool 时
        """
        entry: dict = {
            "type": "message",
            "role": role,
            "content": content,
            "ts": time.time(),
            "index": self._index,
        }
        if model:
            entry["model"] = model
        if tool_calls:
            entry["tool_calls"] = tool_calls
        if tool_use_id:
            entry["tool_use_id"] = tool_use_id

        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    f.flush()
                self._index += 1
                self._last_role = role
        except Exception:
            logger.warning(
                "JSONL 写入失败: %s (role=%s, index=%d)",
                self._path, role, self._index,
                exc_info=True,
            )

    def append_compact_and_rebuild(self, new_messages: list) -> None:
        """写入 compact 标记行，重置 index，然后逐条追加新消息。

        Args:
            new_messages: 压缩后的新 Message 列表。
        """
        compact_line = json.dumps({"type": "compact", "ts": time.time()}, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(compact_line)
                    f.flush()
                self._index = 0
                self._last_role = ""
        except Exception:
            logger.warning("compact 标记写入失败: %s", self._path, exc_info=True)
            return

        # 逐条追加新消息
        for msg in new_messages:
            role = msg.role
            content = msg.content or ""
            if role == "assistant" and msg.tool_calls:
                tcs = [
                    {"id": tc.id, "name": tc.name, "input": tc.arguments}
                    for tc in msg.tool_calls
                ]
                self.append_message("assistant", content, tool_calls=tcs)
            elif role == "user" and msg.tool_result:
                tr = msg.tool_result
                self.append_message(
                    "tool",
                    tr.get("content", ""),
                    tool_use_id=tr.get("tool_use_id", ""),
                )
            else:
                self.append_message(role, content)
