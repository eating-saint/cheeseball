"""替换决策账本（F5, N2）。

记录每个 tool_use_id 的替换决策：保留原文还是替换为预览字符串。
线程安全：所有写操作在 threading.Lock 保护下原子完成。

契约（与 offloader.py）：
- commit_keep / commit_replace 由 offloader 在落盘成功后调用。
- 落盘失败则不调用任何 commit 方法。
- commit_replace 同一锁内同时写 _seen_ids 和 _replacements，不允许中间态。
"""

from __future__ import annotations

import threading


class ReplacementLedger:
    """替换决策账本。线程安全。

    用法::

        ledger = ReplacementLedger()
        ledger.commit_keep("abc")          # 决策：保留原文
        ledger.commit_replace("xyz", "...")  # 决策：替换为预览字符串
        assert ledger.is_seen("abc")
        assert ledger.get_replacement("xyz") == "..."
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def is_seen(self, tool_use_id: str) -> bool:
        """检查 tool_use_id 是否已作出决策。

        Args:
            tool_use_id: 工具调用 ID。

        Returns:
            True 如果已存在决策（无论是 keep 还是 replace）。
        """
        with self._lock:
            return tool_use_id in self._seen_ids

    def get_replacement(self, tool_use_id: str) -> str | None:
        """获取已决策的替换预览字符串。

        Args:
            tool_use_id: 工具调用 ID。

        Returns:
            预览字符串（如果是 replace 决策），否则 None（keep 决策或未决策）。
        """
        with self._lock:
            return self._replacements.get(tool_use_id)

    def commit_keep(self, tool_use_id: str) -> None:
        """原子写入 seen_ids，标记保留原文。

        只写 _seen_ids，不写 _replacements。
        后续 is_seen 返回 True，get_replacement 返回 None → 保持原文不替换。

        Args:
            tool_use_id: 工具调用 ID。
        """
        with self._lock:
            self._seen_ids.add(tool_use_id)

    def commit_replace(self, tool_use_id: str, preview: str) -> None:
        """原子同时写入 seen_ids + replacements，不允许中间态（F5a）。

        同一锁内完成，保证 N2 约束：seen 写入时 replacement 一定也已写入。

        Args:
            tool_use_id: 工具调用 ID。
            preview: 预览字符串（由 offloader._build_preview 生成）。
        """
        with self._lock:
            self._seen_ids.add(tool_use_id)
            self._replacements[tool_use_id] = preview
