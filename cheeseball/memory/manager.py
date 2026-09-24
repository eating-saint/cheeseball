"""两级记忆目录 CRUD + MEMORY.md 索引维护（ch09 F23-F24, F28-F32）."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25 * 1024  # 25KB


@dataclass
class MemoryNote:
    """一条笔记的内存表示。"""

    name: str           # 短 slug（对应文件名不含扩展名）
    description: str    # 一行摘要
    type: str           # "user" | "feedback" | "project" | "reference"
    content: str        # 正文（不含 frontmatter）
    created: str = ""   # ISO 8601
    modified: str = ""  # ISO 8601


class MemoryManager:
    """管理两级记忆目录（项目级 + 用户级）的 CRUD 和索引。

    用法::

        mgr = MemoryManager(
            project_memory_dir=Path(".cheeseball/memory"),
            user_memory_dir=Path.home() / ".cheeseball" / "memory",
        )
        mgr.ensure_dirs()
        mgr.write_note(note, "project")
        index_text = mgr.load_index()
    """

    def __init__(
        self,
        project_memory_dir: Path,
        user_memory_dir: Path,
    ) -> None:
        self._project_dir = project_memory_dir
        self._user_dir = user_memory_dir

    # ── 目录管理 ──────────────────────────────────────────────

    def ensure_dirs(self) -> None:
        """确保两级目录存在。"""
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._user_dir.mkdir(parents=True, exist_ok=True)

    @property
    def project_dir(self) -> Path:
        """返回项目级记忆目录。"""
        return self._project_dir

    @property
    def user_dir(self) -> Path:
        """返回用户级记忆目录。"""
        return self._user_dir

    # ── 索引加载 ──────────────────────────────────────────────

    def load_index(self) -> str:
        """加载两级 MEMORY.md，拼接返回。

        项目级在前，用户级在后，空行分隔。
        文件不存在返回空字符串。
        """
        parts: list[str] = []
        for mem_dir in (self._project_dir, self._user_dir):
            index_path = mem_dir / "MEMORY.md"
            try:
                if index_path.is_file():
                    content = index_path.read_text(encoding="utf-8")
                    if content.strip():
                        parts.append(content.strip())
            except Exception:
                logger.warning("读取 MEMORY.md 失败: %s", index_path, exc_info=True)

        if not parts:
            return ""
        return "\n\n".join(parts)

    # ── 笔记 CRUD ─────────────────────────────────────────────

    def get_all_notes(self) -> tuple[list[MemoryNote], list[MemoryNote]]:
        """返回 (project_notes, user_notes)。"""
        return (
            self._scan_dir(self._project_dir),
            self._scan_dir(self._user_dir),
        )

    def write_note(self, note: MemoryNote, level: str) -> None:
        """写单条笔记 .md 文件，原子写入（.tmp → os.replace）。

        Args:
            note: 要写入的笔记。
            level: "project" 或 "user"。
        """
        mem_dir = self._resolve_dir(level)
        if mem_dir is None:
            return

        mem_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{note.type}_{note.name}.md"
        filepath = mem_dir / filename

        now = note.modified or _now_iso()
        if not note.created:
            note.created = now

        # 构造 frontmatter + 正文
        content = _build_note_markdown(note, now)

        # 原子写入
        tmp_path = filepath.with_suffix(filepath.suffix + ".tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(str(tmp_path), str(filepath))
        except Exception:
            logger.warning("笔记写入失败: %s", filepath, exc_info=True)
            # 清理残留 tmp
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def delete_note(self, filename: str, level: str) -> None:
        """删除单条笔记文件。

        Args:
            filename: 文件名（含 .md 扩展名）。
            level: "project" 或 "user"。
        """
        mem_dir = self._resolve_dir(level)
        if mem_dir is None:
            return

        filepath = mem_dir / filename
        try:
            filepath.unlink(missing_ok=True)
        except Exception:
            logger.warning("笔记删除失败: %s", filepath, exc_info=True)

    def rebuild_index(self, notes: list[MemoryNote], level: str) -> None:
        """重建 MEMORY.md 索引，原子写入。

        Args:
            notes: 笔记列表。
            level: "project" 或 "user"。
        """
        mem_dir = self._resolve_dir(level)
        if mem_dir is None:
            return

        mem_dir.mkdir(parents=True, exist_ok=True)
        index_path = mem_dir / "MEMORY.md"

        lines: list[str] = []
        for note in notes:
            line = f"- [{note.type}] {note.description}"
            lines.append(line)

        # 截断到 200 行
        if len(lines) > MAX_INDEX_LINES:
            lines = lines[:MAX_INDEX_LINES]

        text = "\n".join(lines) + "\n"

        # 截断到 25KB
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_INDEX_BYTES:
            # 逐行删减直到不超过 25KB
            while len(encoded) > MAX_INDEX_BYTES and lines:
                lines.pop()
                text = "\n".join(lines) + "\n"
                encoded = text.encode("utf-8")

        # 原子写入
        tmp_path = index_path.with_suffix(index_path.suffix + ".tmp")
        try:
            tmp_path.write_text(text, encoding="utf-8")
            os.replace(str(tmp_path), str(index_path))
        except Exception:
            logger.warning("索引重建失败: %s", index_path, exc_info=True)
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    # ── 内部方法 ──────────────────────────────────────────────

    def _resolve_dir(self, level: str) -> Path | None:
        """解析 level 到对应目录。"""
        if level == "project":
            return self._project_dir
        elif level == "user":
            return self._user_dir
        else:
            logger.warning("未知的记忆级别: %s", level)
            return None

    def _scan_dir(self, mem_dir: Path) -> list[MemoryNote]:
        """扫描目录下所有 .md 文件（跳过 MEMORY.md），解析 frontmatter。"""
        notes: list[MemoryNote] = []
        try:
            for entry in sorted(mem_dir.iterdir()):
                if not entry.is_file():
                    continue
                if entry.suffix != ".md":
                    continue
                if entry.name == "MEMORY.md":
                    continue
                note = _parse_note_file(entry)
                if note:
                    notes.append(note)
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("扫描记忆目录失败: %s", mem_dir, exc_info=True)
        return notes


# ── 内部辅助函数 ──────────────────────────────────────────────────


def _now_iso() -> str:
    """返回当前时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _build_note_markdown(note: MemoryNote, modified: str) -> str:
    """构造带 frontmatter 的笔记 Markdown 文本。"""
    return (
        "---\n"
        f"name: {note.name}\n"
        f"description: {note.description}\n"
        f"metadata:\n"
        f"  type: {note.type}\n"
        f"created: \"{note.created}\"\n"
        f"modified: \"{modified}\"\n"
        "---\n\n"
        f"{note.content}\n"
    )


def _parse_note_file(filepath: Path) -> MemoryNote | None:
    """从 .md 文件解析 frontmatter 和正文，返回 MemoryNote 或 None。"""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    # 简单 frontmatter 解析（不依赖 PyYAML）
    fm = _parse_frontmatter(text)
    if not fm:
        return None

    name = fm.get("name", filepath.stem)
    description = fm.get("description", "")
    note_type = fm.get("type", "project")
    created = fm.get("created", "")
    modified = fm.get("modified", "")

    # 正文：frontmatter 之后的内容
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()

    return MemoryNote(
        name=name,
        description=description,
        type=note_type,
        content=body,
        created=created,
        modified=modified,
    )


def _parse_frontmatter(text: str) -> dict[str, str]:
    """极简 YAML frontmatter 解析，仅提取顶层 key: value。"""
    if not text.startswith("---"):
        return {}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}

    fm_text = parts[1]
    result: dict[str, str] = {}
    in_metadata = False

    for line in fm_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # metadata 子块
        if stripped == "metadata:":
            in_metadata = True
            continue

        if in_metadata:
            m = re.match(r"^\s+(\w+):\s*(.*)", line)
            if m:
                result[m.group(1)] = m.group(2).strip().strip('"')
                continue
            else:
                in_metadata = False

        m = re.match(r"^(\w+):\s*(.*)", stripped)
        if m:
            result[m.group(1)] = m.group(2).strip().strip('"')

    return result
