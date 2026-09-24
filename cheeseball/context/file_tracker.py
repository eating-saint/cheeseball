"""文件读取追踪（F19-F20, N2）。

记录 Agent 最近读取的文件，供压缩后恢复段使用。
线程安全：record 和 get_recent 在 threading.Lock 保护下操作。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from cheeseball.context.constants import MAX_RECENT_FILES


@dataclass
class FileSnapshot:
    """单个文件读取快照。

    Attributes:
        path: 文件路径。
        read_at: 读取时间戳（time.time()）。
        content_bytes: 文件的原始字节内容（纯净，不带行号前缀）。
    """

    path: str
    read_at: float = field(default_factory=time.time)
    content_bytes: bytes = b""


class FileReadTracker:
    """文件读取追踪器。线程安全。

    用法::

        ft = FileReadTracker()
        ft.record("a.py", b"hello")
        ft.record("b.py", b"world")
        recent = ft.get_recent()  # [FileSnapshot("b.py", ...), FileSnapshot("a.py", ...)]
    """

    MAX_FILES: int = MAX_RECENT_FILES

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileSnapshot] = {}

    def record(self, path: str, content_bytes: bytes) -> None:
        """记录一次文件读取（F19）。

        若路径已存在则覆盖时间戳和内容（同路径文件可能被更新）。
        由 runner.py 在 read_file 成功后、add_tool_results 前调用。

        Args:
            path: 文件路径。
            content_bytes: 文件的原始字节内容（不带动行号前缀）。
        """
        with self._lock:
            self._files[path] = FileSnapshot(
                path=path,
                read_at=time.time(),
                content_bytes=content_bytes,
            )

    def get_recent(self) -> list[FileSnapshot]:
        """获取最近读取的文件快照列表（F20）。

        按 read_at 倒序排列，最多返回 MAX_FILES(5) 个。

        Returns:
            按读取时间倒序的 FileSnapshot 列表。
        """
        with self._lock:
            sorted_files = sorted(
                self._files.values(),
                key=lambda s: s.read_at,
                reverse=True,
            )
            return sorted_files[: self.MAX_FILES]
