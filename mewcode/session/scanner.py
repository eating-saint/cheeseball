"""会话扫描与过期清理（ch09 F16-F22）."""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 50


@dataclass
class SessionMeta:
    """扫描 JSONL 提取的会话元信息。"""

    session_id: str             # 目录名 = session id
    title: str                  # 首条 user 消息 content，截断到 50 字符
    message_count: int          # 消息行数（不含 compact 标记）
    model: str                  # 从第一条 assistant 消息的 model 字段提取
    file_size: int              # conversation.jsonl 字节数
    mtime: float                # 文件最后修改时间（Unix 时间戳）
    last_compact_ts: float | None = None


def scan_sessions(sessions_root: Path) -> list[SessionMeta]:
    """扫描 sessions 目录下所有有效会话，按 mtime 倒序排列。

    Args:
        sessions_root: sessions 根目录。

    Returns:
        按 mtime 倒序排列的会话元信息列表。
    """
    result: list[SessionMeta] = []

    if not sessions_root.is_dir():
        return result

    for entry in sorted(sessions_root.iterdir()):
        if not entry.is_dir():
            continue

        jsonl_path = entry / "conversation.jsonl"
        if not jsonl_path.is_file():
            continue

        try:
            meta = _scan_jsonl(entry.name, jsonl_path)
            if meta:
                result.append(meta)
        except Exception:
            logger.warning("扫描会话失败: %s", entry.name, exc_info=True)

    # 按 mtime 倒序
    result.sort(key=lambda m: m.mtime, reverse=True)
    return result


def cleanup_expired(
    sessions_root: Path,
    max_age_days: int = 30,
    protected_id: str | None = None,
) -> int:
    """删除超过 max_age_days 天未修改的会话目录。

    Args:
        sessions_root: sessions 根目录。
        max_age_days: 最大保留天数。
        protected_id: 受保护的 session_id（不删除）。

    Returns:
        删除的目录数。
    """
    if not sessions_root.is_dir():
        return 0

    now = time.time()
    max_age_seconds = max_age_days * 86400
    deleted = 0

    for entry in sorted(sessions_root.iterdir()):
        if not entry.is_dir():
            continue

        if entry.name == protected_id:
            continue

        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue

        if now - mtime > max_age_seconds:
            try:
                shutil.rmtree(str(entry))
                deleted += 1
                logger.info("清理过期会话: %s", entry.name)
            except Exception:
                logger.warning("清理会话失败: %s", entry.name, exc_info=True)

    if deleted > 0:
        logger.info("会话清理完成: %d 个过期会话已删除", deleted)
    return deleted


def _scan_jsonl(session_id: str, jsonl_path: Path) -> SessionMeta | None:
    """从 JSONL 文件提取会话元信息。"""
    title = ""
    model = ""
    message_count = 0
    last_compact_ts = None

    try:
        stat = jsonl_path.stat()
        file_size = stat.st_size
        mtime = stat.st_mtime
    except OSError:
        return None

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") == "compact":
                    last_compact_ts = obj.get("ts")
                    continue

                if obj.get("type") != "message":
                    continue

                message_count += 1
                role = obj.get("role", "")

                # 标题：第一条 user 消息
                if not title and role == "user":
                    content = obj.get("content", "")
                    title = _truncate_title(content)

                # 模型：第一条 assistant 消息
                if not model and role == "assistant":
                    model = obj.get("model", "")

    except Exception:
        pass

    return SessionMeta(
        session_id=session_id,
        title=title or "(空会话)",
        message_count=message_count,
        model=model or "unknown",
        file_size=file_size,
        mtime=mtime,
        last_compact_ts=last_compact_ts,
    )


def _truncate_title(content: str) -> str:
    """截断标题到 MAX_TITLE_LENGTH 字符。"""
    content = content.replace("\n", " ").strip()
    if len(content) <= MAX_TITLE_LENGTH:
        return content
    return content[:MAX_TITLE_LENGTH] + "..."
