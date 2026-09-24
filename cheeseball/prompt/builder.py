"""系统提示装配器：模块注册、稳定/环境区拼接、reminder 委托。

对外产出三类文本：
- build_stable()：稳定模块拼接，可缓存
- build_environment()：环境信息，静态不缓存（后续加 cache_control）
- build_reminder()：<system-reminder> 补充指令
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys

from cheeseball.prompt.modules import DEFAULT_MODULES, Module
from cheeseball.prompt.reminder import build_reminder as _build_reminder


# ── 环境检测辅助函数 ────────────────────────────────────────────


def _detect_shell() -> str:
    """检测当前进程所在的 shell 类型。

    Windows:
        PSMODULEPATH 环境变量存在 → PowerShell
        否则 → cmd.exe

    Unix:
        读 SHELL 环境变量取 basename；回退检查 BASH_VERSION / ZSH_VERSION。
    """
    if os.name == "nt":
        if "PSMODULEPATH" in os.environ:
            return "PowerShell"
        return "cmd.exe"

    # Unix
    shell = os.environ.get("SHELL", "")
    if shell:
        return os.path.basename(shell)

    if "BASH_VERSION" in os.environ:
        return "bash"
    if "ZSH_VERSION" in os.environ:
        return "zsh"

    return "unknown"


def _detect_python_info() -> str | None:
    """如果工作目录下存在 Python 项目标识文件，返回 Python 版本 + conda 信息。

    触发条件：requirements.txt 或 pyproject.toml 存在于 cwd。
    额外检测 conda 环境（CONDA_DEFAULT_ENV / CONDA_PREFIX / sys.prefix）。
    """
    cwd = os.getcwd()
    has_python_project = (
        os.path.isfile(os.path.join(cwd, "requirements.txt"))
        or os.path.isfile(os.path.join(cwd, "pyproject.toml"))
    )
    if not has_python_project:
        return None

    v = sys.version_info
    result = f"Python {v.major}.{v.minor}.{v.micro}"

    # conda 检测
    conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if conda_env:
        result += f"（conda 环境: {conda_env}）"
    elif os.environ.get("CONDA_PREFIX", ""):
        result += "（conda 环境）"
    elif "conda" in sys.prefix.lower():
        result += "（conda 环境）"

    return result


def _detect_node_version() -> str | None:
    """如果工作目录下存在 package.json，返回 Node 版本号。

    触发条件：package.json 存在于 cwd。
    通过 `node --version` 获取版本，失败则返回 None。
    """
    cwd = os.getcwd()
    if not os.path.isfile(os.path.join(cwd, "package.json")):
        return None

    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            # node --version 输出类似 "v20.10.0"
            return f"Node {version}"
    except Exception:
        pass

    return None


def _detect_git_status() -> str | None:
    """如果工作目录是 git 仓库，返回分支名 + 工作区状态。

    不是 git 仓库则返回 None。git 未安装也返回 None。
    """
    cwd = os.getcwd()
    if not os.path.exists(os.path.join(cwd, ".git")):
        return None

    try:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if branch_result.returncode != 0:
            return None
        branch = branch_result.stdout.strip()

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        if status_result.returncode == 0:
            if status_result.stdout.strip():
                return f"当前分支 {branch}，有未提交的改动"
            else:
                return f"当前分支 {branch}，工作区干净"

        return f"当前分支 {branch}"
    except Exception:
        return None


# ── Builder ──────────────────────────────────────────────────────


class SystemPromptBuilder:
    """系统提示装配器，管理模块注册与三类文本产出。

    用法::

        builder = SystemPromptBuilder()
        stable = builder.build_stable()        # 可缓存
        env = builder.build_environment()       # 会话内静态，后续加 cache_control
        reminder = builder.build_reminder(mode="plan", iteration=3)
    """

    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}
        for m in DEFAULT_MODULES:
            self.register(m)

    # ── 模块管理 ──────────────────────────────────────────────

    def register(self, module: Module) -> None:
        """注册或覆盖一个模块。同名模块后者覆盖前者（支持 N5 覆盖）。"""
        self._modules[module.id] = module

    # ── 文本产出 ──────────────────────────────────────────────

    def build_stable(self) -> str:
        """返回 stable=True 的模块按 priority 升序拼接的文本。

        模块间以双换行分隔。此文本在会话内跨轮次逐字节稳定，
        可放入 API 的缓存通道。
        """
        stable_modules = sorted(
            [m for m in self._modules.values() if m.stable],
            key=lambda m: m.priority,
        )
        return "\n\n".join(m.content for m in stable_modules)

    def build_environment(self) -> str:
        """返回环境信息文本（会话内静态，后续加 cache_control）。

        包含 OS、Shell、工作目录，以及按需检测的
        语言运行时版本和 Git 状态。

        同时附加 stable=False 的模块内容（如有）。
        """
        parts: list[str] = []

        # stable=False 的模块
        dynamic_modules = sorted(
            [m for m in self._modules.values() if not m.stable],
            key=lambda m: m.priority,
        )
        for m in dynamic_modules:
            parts.append(m.content)

        # 静态环境信息
        env_lines = [
            f"- 操作系统：{platform.system()} {platform.release()}",
            f"- Shell：{_detect_shell()}",
            f"- 工作目录：{os.getcwd()}",
        ]

        # 语言与运行时（按需）
        runtime_parts: list[str] = []
        py_info = _detect_python_info()
        if py_info:
            runtime_parts.append(py_info)
        node_ver = _detect_node_version()
        if node_ver:
            runtime_parts.append(node_ver)
        if runtime_parts:
            env_lines.append(f"- 语言与运行时：{'；'.join(runtime_parts)}")

        # Git 状态（按需）
        git_status = _detect_git_status()
        if git_status:
            env_lines.append(f"- Git：{git_status}")

        parts.append("环境信息：\n" + "\n".join(env_lines))

        return "\n\n".join(parts)

    def build_reminder(self, *, mode: str, iteration: int) -> str:
        """构造本轮 <system-reminder> 补充指令。

        Args:
            mode: "normal" 或 "plan"。
            iteration: 当前迭代轮次（从 1 开始）。

        Returns:
            <system-reminder> 包裹的文本，normal 模式返回空字符串。
        """
        return _build_reminder(mode=mode, iteration=iteration)
