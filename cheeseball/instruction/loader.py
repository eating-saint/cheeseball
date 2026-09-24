"""CHEESEBALL.md 三层加载 + @include 展开（ch09 F1-F8）."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_INCLUDE_DEPTH = 5


@dataclass
class IncludeWarning:
    """@include 展开过程中产生的警告。"""

    path: str       # 原始引用路径
    reason: str     # "not_found" | "max_depth" | "cycle" | "escape" | "binary"


@dataclass
class InstructionResult:
    """三层 CHEESEBALL.md 加载 + @include 展开的最终结果。"""

    text: str = ""                          # 拼接后的完整指令文本
    warnings: list[IncludeWarning] = field(default_factory=list)
    loaded_layers: list[str] = field(default_factory=list)  # 实际加载了的文件路径
    total_bytes: int = 0                    # 总字节数
    include_count: int = 0                  # 成功展开的 @include 次数


# ── 公开接口 ──────────────────────────────────────────────────────


def load_instructions(
    project_root: Path,
    read_file: Callable[[Path], str | None] | None = None,
) -> InstructionResult:
    """启动时加载三层 CHEESEBALL.md 并展开 @include。

    Args:
        project_root: 项目根目录。
        read_file: 文件读取函数，可注入用于测试。默认使用 Path.read_text()。

    Returns:
        InstructionResult 包含拼接后的完整指令文本、警告、加载层等。
    """
    if read_file is None:
        def _default_read(p: Path) -> str | None:
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return None
        read_file = _default_read

    result = InstructionResult()
    project_root = project_root.resolve()
    user_cheeseball_dir = Path.home() / ".cheeseball"

    # 三层路径（F1）：优先级从高到低
    layers: list[tuple[Path, Path]] = [
        (project_root / "CHEESEBALL.md", project_root),                    # ① 项目级
        (project_root / ".cheeseball" / "CHEESEBALL.md", project_root),       # ② 项目配置级
        (user_cheeseball_dir / "CHEESEBALL.md", user_cheeseball_dir),            # ③ 用户级
    ]

    parts: list[str] = []
    for file_path, root_boundary in layers:
        layer_text = _load_layer(file_path, read_file)
        if layer_text is None:
            continue

        result.loaded_layers.append(str(file_path))

        # 展开 @include
        expanded, w = _expand_includes(
            layer_text,
            current_dir=file_path.parent,
            root_boundary=root_boundary,
            visited=set(),
            depth=1,
            read_file=read_file,
        )
        result.warnings.extend(w)
        result.include_count += sum(
            1 for ww in w if ww.reason == "not_found"
        )
        # Actually count successful includes (not warnings)
        # Re-count: successful includes don't produce warnings
        result.include_count = _count_includes(layer_text, file_path.parent,
                                                root_boundary, set(), 1, read_file)

        parts.append(expanded)

    result.text = "\n\n".join(parts)
    result.total_bytes = len(result.text.encode("utf-8"))

    # 日志（N16）
    logger.info(
        "指令加载完成: %d 层, %d 字节, %d @include 展开, %d 警告",
        len(result.loaded_layers),
        result.total_bytes,
        result.include_count,
        len(result.warnings),
    )
    for w in result.warnings:
        logger.info("  @include 跳过: %s (原因: %s)", w.path, w.reason)

    return result


# ── 内部函数 ──────────────────────────────────────────────────────


def _load_layer(path: Path, read_file: Callable[[Path], str | None]) -> str | None:
    """读单层 CHEESEBALL.md，不存在或编码错误返回 None。"""
    try:
        if not path.is_file():
            return None
    except OSError:
        return None

    try:
        content = read_file(path)
        if content is None:
            return None
        return content
    except Exception:
        logger.warning("指令文件读取失败: %s", path, exc_info=True)
        return None


def _count_includes(
    text: str,
    current_dir: Path,
    root_boundary: Path,
    visited: set[Path],
    depth: int,
    read_file: Callable[[Path], str | None],
) -> int:
    """递归统计成功展开的 @include 次数。"""
    count = 0
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("@include "):
            continue

        ref_path = stripped[len("@include "):].strip()
        if not ref_path:
            continue

        # 解析绝对路径
        try:
            abs_path = (current_dir / ref_path).resolve()
        except Exception:
            continue

        if depth >= MAX_INCLUDE_DEPTH:
            continue
        if abs_path in visited:
            continue
        if not str(abs_path).startswith(str(root_boundary)):
            continue
        if not abs_path.is_file():
            continue

        # 读文件
        try:
            content = read_file(abs_path)
        except Exception:
            continue
        if content is None:
            continue
        if _is_binary(content):
            continue

        count += 1
        new_visited = visited | {abs_path}
        count += _count_includes(content, abs_path.parent, root_boundary,
                                 new_visited, depth + 1, read_file)
    return count


def _expand_includes(
    text: str,
    current_dir: Path,
    root_boundary: Path,
    visited: set[Path],
    depth: int,
    read_file: Callable[[Path], str | None],
) -> tuple[str, list[IncludeWarning]]:
    """递归展开 @include 行。

    Args:
        text: 当前文件内容。
        current_dir: 当前文件所在目录（用于解析相对路径）。
        root_boundary: 路径逃逸检测的根边界。
        visited: 已访问的绝对路径集合（环路检测）。
        depth: 当前嵌套深度（CHEESEBALL.md 本身为第 1 层）。
        read_file: 文件读取函数。

    Returns:
        (展开后的文本, 警告列表)
    """
    warnings: list[IncludeWarning] = []
    result_lines: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()

        # 检查是否为独占一行的 @include <path>
        if not stripped.startswith("@include "):
            result_lines.append(line)
            continue

        ref_path = stripped[len("@include "):].strip()
        if not ref_path:
            result_lines.append(line)
            continue

        # ── 规则检查 ──

        # 深度限制（F3）
        if depth >= MAX_INCLUDE_DEPTH:
            result_lines.append(line)
            result_lines.append(
                f"<!-- @include 超过最大嵌套深度，已跳过: {ref_path} -->"
            )
            warnings.append(IncludeWarning(path=ref_path, reason="max_depth"))
            continue

        # 解析绝对路径
        try:
            abs_path = (current_dir / ref_path).resolve()
        except Exception:
            result_lines.append(line)
            continue

        # 环路检测（F4）
        if abs_path in visited:
            result_lines.append(line)
            result_lines.append(
                f"<!-- @include 检测到环路，已跳过: {ref_path} -->"
            )
            warnings.append(IncludeWarning(path=ref_path, reason="cycle"))
            continue

        # 路径逃逸检测（F5）
        if not str(abs_path).startswith(str(root_boundary)):
            result_lines.append(line)
            result_lines.append(
                f"<!-- @include 路径超出允许范围，已跳过: {ref_path} -->"
            )
            warnings.append(IncludeWarning(path=ref_path, reason="escape"))
            continue

        # 文件不存在（F6：静默跳过）
        try:
            if not abs_path.is_file():
                result_lines.append(line)
                # 静默跳过，不警告
                continue
        except OSError:
            result_lines.append(line)
            continue

        # 读取文件
        try:
            content = read_file(abs_path)
        except Exception:
            result_lines.append(line)
            continue

        if content is None:
            result_lines.append(line)
            continue

        # 二进制文件检测（F6）
        if _is_binary(content):
            result_lines.append(line)
            result_lines.append(
                f"<!-- @include 文件为二进制格式，已跳过: {ref_path} -->"
            )
            warnings.append(IncludeWarning(path=ref_path, reason="binary"))
            continue

        # ── 递归展开 ──
        new_visited = visited | {abs_path}
        expanded, sub_warnings = _expand_includes(
            content,
            current_dir=abs_path.parent,
            root_boundary=root_boundary,
            visited=new_visited,
            depth=depth + 1,
            read_file=read_file,
        )
        result_lines.append(expanded)
        warnings.extend(sub_warnings)

    return "\n".join(result_lines), warnings


def _is_binary(content: str) -> bool:
    """前 512 字节含 \\x00 视为二进制文件。"""
    sample = content[:512]
    return "\x00" in sample
