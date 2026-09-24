"""UI 控制抽象接口（F4, F30-F32）。

Handler 通过此接口与 TUI 交互，不直接持有 TUI App 引用。
不导入 Textual 类型（N3, AC27）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class UICtl(ABC):
    """命令与 UI 之间的抽象接口。

    共 19 个方法，分为四组：输出、对话注入、状态查询、界面操作。
    """

    # ── 输出 ──

    @abstractmethod
    def show_info(self, text: str) -> None:
        """在对话区显示信息性文本。"""
        ...

    @abstractmethod
    def show_error(self, text: str) -> None:
        """在对话区显示错误文本。"""
        ...

    # ── 对话注入 ──

    @abstractmethod
    def inject_user_message(self, text: str) -> None:
        """将文本作为 user message 注入对话，走正常 Agent 流（F8, F17）。"""
        ...

    # ── 状态查询（F13: /status 6 字段） ──

    @abstractmethod
    def get_permission_mode(self) -> str:
        """返回当前权限模式字符串。"""
        ...

    @abstractmethod
    def get_token_input(self) -> int:
        """返回累计输入 token 数。"""
        ...

    @abstractmethod
    def get_token_output(self) -> int:
        """返回累计输出 token 数。"""
        ...

    @abstractmethod
    def get_tool_count(self) -> int:
        """返回可用工具数量。"""
        ...

    @abstractmethod
    def get_memory_count(self) -> int:
        """返回已加载记忆条目数。"""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """返回当前模型名。"""
        ...

    @abstractmethod
    def get_work_dir(self) -> str:
        """返回当前工作目录。"""
        ...

    # ── 界面操作 ──

    @abstractmethod
    def set_permission_mode(self, mode: str) -> None:
        """切换权限模式（F7, F8）。"""
        ...

    @abstractmethod
    def clear_conversation(self) -> None:
        """关闭旧存档 → 新存档 → 清空消息 → token 归零（F11）。"""
        ...

    @abstractmethod
    def trigger_compact(self) -> None:
        """手动触发上下文压缩（F9）。"""
        ...

    @abstractmethod
    def open_session_list(self) -> None:
        """打开历史会话列表（F10）。"""
        ...

    @abstractmethod
    def exit_app(self) -> None:
        """关闭 TUI 进程（F6）。"""
        ...

    # ── 状态查询 2 ──

    @abstractmethod
    def is_idle(self) -> bool:
        """返回当前是否可执行 UI/PROMPT 类命令（N3a）。"""
        ...

    @abstractmethod
    def get_session_id(self) -> str:
        """返回当前会话 ID（F16）。"""
        ...

    @abstractmethod
    def get_archive_path(self) -> str:
        """返回当前会话存档 JSONL 文件路径（F16）。"""
        ...

    @abstractmethod
    def get_memory_file_names(self) -> list[str]:
        """返回已加载记忆文件名列表（F14）。"""
        ...
