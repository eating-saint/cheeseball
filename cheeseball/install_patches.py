"""启动时自动修复 Textual/Rich 上游库的已知 bug。

每个 patch 都是源码级修改（直接改 pip 安装的 .py 文件），不是 monkey-patch。
上游 issue:
  - Textual #6667: VK=0 filter discards CJK IME composition events
  - Rich   #4197: EAW='A' characters return wrong cell width on CJK terminals
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PATCH_VK0_MARKER = 'and (not key or key == "\\x00")'
_PATCH_EAW_MARKER = "unicodedata.east_asian_width"


def ensure_patches() -> None:
    """应用所有必要的上游库补丁（幂等：已应用的跳过）。"""
    _patch_win32_vk0()
    _patch_cells_eaw()


# ──────────────────────────────────────────────────────────
# Patch 1: Textual win32.py — VK=0 filter CJK IME fix
# ──────────────────────────────────────────────────────────


def _patch_win32_vk0() -> None:
    """修复 win32.py 的 VK=0 过滤器，放行含有有效 Unicode 字符的 IME 事件。"""
    path = _find_package_file("textual.drivers", "win32.py")
    if path is None:
        logger.warning("[cheeseball] textual.drivers.win32 not found, skip VK=0 patch")
        return

    content = path.read_text(encoding="utf-8")

    if _PATCH_VK0_MARKER in content:
        logger.debug("[cheeseball] patch win32_vk0 already applied")
        return

    # 原版上游代码：
    original = (
        "            if (\n"
        "                key_event.dwControlKeyState\n"
        "                and key_event.wVirtualKeyCode == 0\n"
        "            ):\n"
        "                continue"
    )
    patched = (
        "            if (\n"
        "                key_event.dwControlKeyState\n"
        "                and key_event.wVirtualKeyCode == 0\n"
        "                and (not key or key == \"\\x00\")\n"
        "            ):\n"
        "                continue"
    )

    if original not in content:
        logger.warning(
            "[cheeseball] win32_vk0: upstream win32.py changed — "
            "cannot find expected VK=0 filter block. "
            "The patch may need updating."
        )
        return

    _backup(path)
    content = content.replace(original, patched, 1)
    path.write_text(content, encoding="utf-8")
    logger.info(
        "[cheeseball] patch win32_vk0 applied — CJK IME Shift+symbol events "
        "no longer discarded by VK=0 filter"
    )


# ──────────────────────────────────────────────────────────
# Patch 2: Rich cells.py — EAW='A' → width=2 on CJK terminals
# ──────────────────────────────────────────────────────────


def _patch_cells_eaw() -> None:
    """修复 get_character_cell_size() 对 EAW='A' 字符返回错误的 cell width。"""
    path = _find_package_file("rich", "cells.py")
    if path is None:
        logger.warning("[cheeseball] rich.cells not found, skip EAW patch")
        return

    content = path.read_text(encoding="utf-8")

    if _PATCH_EAW_MARKER in content:
        logger.debug("[cheeseball] patch cells_eaw already applied")
        return

    changed = False

    # --- 3a: 顶部加 import unicodedata ---
    old_import = (
        "from functools import lru_cache\n"
        "from operator import itemgetter\n"
        "from typing import Callable, NamedTuple, Sequence, Tuple\n"
        "\n"
        "from rich._unicode_data import load as load_cell_table"
    )
    new_import = (
        "import unicodedata\n"
        "from functools import lru_cache\n"
        "from operator import itemgetter\n"
        "from typing import Callable, NamedTuple, Sequence, Tuple\n"
        "\n"
        "from rich._unicode_data import load as load_cell_table"
    )
    if old_import in content:
        content = content.replace(old_import, new_import, 1)
        changed = True
    elif "import unicodedata" not in content:
        logger.warning(
            "[cheeseball] cells_eaw: cannot find import block in cells.py"
        )

    # --- 3b: 第一个 return 1 路径（codepoint > last table entry） ---
    old_fallback1 = (
        "    last_entry = table[-1]\n"
        "    if codepoint > last_entry[1]:\n"
        "        return 1"
    )
    new_fallback1 = (
        "    last_entry = table[-1]\n"
        "    if codepoint > last_entry[1]:\n"
        "        if unicodedata.east_asian_width(character) == 'A':\n"
        "            return 2\n"
        "        return 1"
    )
    if old_fallback1 in content:
        content = content.replace(old_fallback1, new_fallback1, 1)
        changed = True
    else:
        logger.warning(
            "[cheeseball] cells_eaw: cannot find first return-1 fallback in cells.py"
        )

    # --- 3c: 第二个 return 1 路径（二进制搜索 fallthrough） ---
    old_fallback2 = (
        "            return width\n"
        "    return 1"
    )
    new_fallback2 = (
        "            return width\n"
        "    if unicodedata.east_asian_width(character) == 'A':\n"
        "        return 2\n"
        "    return 1"
    )
    if old_fallback2 in content:
        content = content.replace(old_fallback2, new_fallback2, 1)
        changed = True
    else:
        logger.warning(
            "[cheeseball] cells_eaw: cannot find second return-1 fallback in cells.py"
        )

    if changed:
        _backup(path)
        path.write_text(content, encoding="utf-8")
        logger.info(
            "[cheeseball] patch cells_eaw applied — EAW='A' characters "
            "now return width=2 on CJK terminals"
        )
    else:
        logger.warning(
            "[cheeseball] cells_eaw: no modifications were made — "
            "upstream cells.py may have changed significantly"
        )


# ──────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────


def _find_package_file(package: str, filename: str) -> Path | None:
    """用 importlib 找到包的安装路径，返回其下文件的绝对路径。"""
    try:
        spec = importlib.util.find_spec(package)
    except (ModuleNotFoundError, ImportError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    # spec.origin 指向包的 __init__.py，取其目录
    pkg_dir = Path(spec.origin).parent
    target = pkg_dir / filename
    return target if target.is_file() else None


def _backup(path: Path) -> None:
    """创建 .cheeseball.bak 备份（如果尚未备份）。"""
    bak = path.with_suffix(path.suffix + ".cheeseball.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
