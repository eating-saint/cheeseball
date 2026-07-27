"""UICtl 的具体实现（F30-F32, T10）。

包装 MewCodeApp，代理所有方法到 app 的对应方法/属性。
Handler 只看到 UICtl 接口，不暴露 MewCodeApp 类型。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from mewcode.cmd.uictl import UICtl

if TYPE_CHECKING:
    from mewcode.ui.app import MewCodeApp


class UICtlImpl(UICtl):
    """UICtl 的具体实现，持有 MewCodeApp 引用。"""

    def __init__(self, app: MewCodeApp) -> None:
        self._app = app

    # ── 输出 ──

    def show_info(self, text: str) -> None:
        self._app._chat_history.show_info(text)

    def show_error(self, text: str) -> None:
        self._app._chat_history.show_error(text)

    # ── 对话注入 ──

    def inject_user_message(self, text: str) -> None:
        """将文本作为 user message 注入并立即触发 Agent 回合（F8, F17）。"""
        self._app._chat_history.append_user_message(text)
        self._app._start_worker(text, plan_mode=False)

    # ── 状态查询（F13 六字段，N8 固定顺序） ──

    def get_permission_mode(self) -> str:
        return self._app._agent._perm_mode.value

    def get_token_input(self) -> int:
        return self._app._total_input_tokens

    def get_token_output(self) -> int:
        return self._app._total_output_tokens

    def get_tool_count(self) -> int:
        registry = self._app._tool_registry
        if registry is None:
            return 0
        return len(registry.export_definitions())

    def get_memory_count(self) -> int:
        memories = self._app._memories
        if not memories:
            return 0
        return len([m for m in memories.splitlines() if m.strip()])

    def get_model_name(self) -> str:
        try:
            return self._app._agent._provider.model_name
        except Exception:
            return "unknown"

    def get_work_dir(self) -> str:
        return os.getcwd()

    # ── 界面操作 ──

    def set_permission_mode(self, mode: str) -> None:
        """切换权限模式（F7, F8）。

        Args:
            mode: "plan" 或 "default"。
        """
        from mewcode.permission.modes import Mode

        mode_map = {
            "plan": Mode.PLAN,
            "default": Mode.DEFAULT,
        }
        target = mode_map.get(mode)
        if target is None:
            self.show_error(f"未知权限模式: {mode}")
            return

        self._app._agent._perm_mode = target
        self._app._agent._perm_engine.mode = target
        self._app._update_perm_status(target)

    def clear_conversation(self) -> None:
        """关闭旧存档 → 开新存档 → 清空消息 → token 归零（F11）。"""
        app = self._app

        # 关闭旧 archiver
        if app._session_archiver is not None:
            app._session_archiver.close()

        # 新 session_id + 新存档
        from mewcode.session import new_session_id

        new_id = new_session_id()
        session_dir = Path.cwd() / ".mewcode" / "sessions" / new_id
        tool_results_dir = session_dir / "tool-results"
        os.makedirs(tool_results_dir, exist_ok=True)

        jsonl_path = session_dir / "conversation.jsonl"
        from mewcode.session.archiver import SessionArchiver

        app._session_archiver = SessionArchiver(jsonl_path)

        # 更新 conversation 的 archiver
        app._conversation._archiver = app._session_archiver

        # 清空消息
        app._conversation.rebuild_messages([])

        # token 归零
        app._total_input_tokens = 0
        app._total_output_tokens = 0

        # 清空 UI
        app._chat_history.clear()

    def trigger_compact(self) -> None:
        """手动触发上下文压缩（F9），复用现有 compact 逻辑。"""
        app = self._app

        if not app._is_streaming and app._context_mgr is not None:
            app._chat_history.show_info("正在压缩上下文...")
            tools = app._current_tools if app._current_tools else []

            async def _do_compact():
                try:
                    from mewcode.prompt import SystemPromptBuilder
                    builder = SystemPromptBuilder()
                    stable = builder.build_stable()
                    env = builder.build_environment()
                    result = await app._context_mgr.compact(
                        app._conversation, tools, stable, env, trigger="manual"
                    )
                    app._chat_history.show_info(
                        f"已压缩，token 从 {result.before_tokens} 降至 {result.after_tokens}"
                    )
                except Exception as e:
                    app._chat_history.show_error(f"压缩失败: {e}")

            asyncio.create_task(_do_compact())

    def open_session_list(self) -> None:
        """打开历史会话列表（F10），复用 ch09 的 /resume 逻辑。"""
        app = self._app
        app._phase = app._phase.__class__.RESUMING
        app.run_worker(
            app._cmd_resume(),
            exclusive=False, thread=False, exit_on_error=False,
        )

    def exit_app(self) -> None:
        """关闭 TUI（F6, N12）：先 cancel Agent，再退出。"""
        self._app._agent.cancel()
        self._app.exit()

    # ── 状态查询 2 ──

    def is_idle(self) -> bool:
        return self._app._phase.value == self._app._phase.IDLE.value

    def get_session_id(self) -> str:
        archiver = self._app._session_archiver
        if archiver is not None:
            path = getattr(archiver, "_path", None)
            if path is not None:
                return str(Path(path).parent.name)
        return "unknown"

    def get_archive_path(self) -> str:
        archiver = self._app._session_archiver
        if archiver is not None:
            path = getattr(archiver, "_path", None)
            if path is not None:
                return str(path)
        return "unknown"

    def get_memory_file_names(self) -> list[str]:
        mgr = self._app._memory_manager
        if mgr is None:
            return []
        names: list[str] = []
        for mem_dir in (mgr._project_dir, mgr._user_dir):
            if mem_dir is not None and mem_dir.exists():
                for f in sorted(mem_dir.glob("*.md")):
                    names.append(f.name)
        return names
