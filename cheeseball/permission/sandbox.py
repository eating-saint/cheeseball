"""第 2 层：路径沙箱。

文件类工具的 path 参数限定在项目根目录内。
解析符号链接防止逃逸。
"""

from __future__ import annotations

import os
from pathlib import Path


class PathSandbox:
    """对文件类工具的 path 参数做沙箱检查。

    解析符号链接，检查真实路径是否以项目根目录为前缀。
    """

    def __init__(self, project_root: str) -> None:
        self._root = Path(project_root).resolve()

    def validate(self, path: str) -> tuple[bool, str]:
        """检查路径是否在项目根目录内。

        Args:
            path: 待检查的路径字符串（相对或绝对）。

        Returns:
            (allowed, reason): allowed=False 表示超出沙箱范围。
        """
        # 1. 转为绝对路径
        p = Path(path)
        if not p.is_absolute():
            abs_path = (self._root / p).resolve()
        else:
            abs_path = p.resolve()

        # 2. 解析符号链接得到真实路径
        try:
            real_path = abs_path.resolve()
        except (OSError, RuntimeError):
            # resolve() 可能因权限等问题失败，回退到不解析
            real_path = abs_path

        # 3. 如果路径尚不存在（write_file 新建文件场景），解析父目录
        if not real_path.exists():
            try:
                parent_real = real_path.parent.resolve()
            except (OSError, RuntimeError):
                parent_real = real_path.parent
            real_path = parent_real / real_path.name

        # 4. 前缀检查
        root_str = str(self._root)
        real_str = str(real_path)
        if real_str == root_str or real_str.startswith(root_str + os.sep):
            return True, ""

        return False, f"SANDBOX: {path} 超出沙箱范围"
