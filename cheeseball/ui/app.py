"""UI 层：Textual 主 App，组合 widget，协调 Agent 多轮循环（ch09 记忆与持久化）."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from enum import Enum, auto
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from cheeseball.agent.events import (
    PermissionChoice,
    PermissionRequest,
    PermissionResponse,
    StopReason,
)
from cheeseball.agent.runner import Agent
from cheeseball.cmd import CommandRegistry, Parser, dispatch as cmd_dispatch
from cheeseball.core.conversation import Conversation
from cheeseball.prompt.modules import Module
from cheeseball.ui.autocomplete import AutocompleteMenu
from cheeseball.ui.chat_history import ChatHistory
from cheeseball.ui.chat_input import ChatInput
from cheeseball.ui.uictl_impl import UICtlImpl


class AppPhase(Enum):
    """TUI 顶层状态（ch09 F35）。与 AgentState 的区别：
    - AgentState 管单次 Agent.run() 内部循环
    - AppPhase 管 TUI 顶层状态
    两者的 IDLE 含义不同，归属不同模块。
    """
    IDLE = auto()       # 可接受输入、可 /resume
    RUNNING = auto()    # Agent.run 执行中，不可 /resume
    RESUMING = auto()   # 正在浏览会话列表，不可发起新对话


class PermissionDialog(ModalScreen[PermissionResponse]):
    """权限确认模态对话框。

    展示工具名、参数预览、原因，三个选项可键盘导航。
    """

    CSS = """
    PermissionDialog {
        align: center middle;
    }

    #perm-dialog {
        width: 56;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #perm-dialog-title {
        text-style: bold;
        color: $warning;
    }

    #perm-dialog-body {
        margin: 1 0;
    }

    #perm-dialog-reason {
        color: $text-muted;
        margin-bottom: 1;
    }

    .perm-option {
        padding: 0 2;
        width: 100%;
    }

    .perm-option-highlighted {
        background: $accent;
        color: $text;
        padding: 0 2;
        width: 100%;
    }
    """

    def __init__(self, request: PermissionRequest) -> None:
        super().__init__()
        self._request = request
        self._options = [
            ("允许本次 (1)", PermissionChoice.ALLOW_ONCE),
            ("永久允许 (2)", PermissionChoice.ALLOW_ALWAYS),
            ("拒绝本次 (3)", PermissionChoice.DENY_ONCE),
        ]
        self._selected = 0  # 默认高亮第一项

    def compose(self) -> ComposeResult:
        with Vertical(id="perm-dialog"):
            yield Static("━ 权限确认 ━", id="perm-dialog-title")
            yield Static(
                f"{self._request.tool_name}({self._request.args_preview})",
                id="perm-dialog-body",
            )
            yield Static(self._request.reason, id="perm-dialog-reason")
            for i, (label, _) in enumerate(self._options):
                cls = "perm-option-highlighted" if i == self._selected else "perm-option"
                yield Static(label, classes=cls, id=f"perm-opt-{i}")

    def on_key(self, event) -> None:
        """键盘导航。"""
        if event.key == "up":
            self._selected = (self._selected - 1) % len(self._options)
            self._refresh_highlight()
            event.stop()
        elif event.key == "down":
            self._selected = (self._selected + 1) % len(self._options)
            self._refresh_highlight()
            event.stop()
        elif event.key == "enter":
            _, choice = self._options[self._selected]
            self.dismiss(PermissionResponse(
                tool_name=self._request.tool_name,
                choice=choice,
            ))
            event.stop()
        elif event.key in ("1", "2", "3"):
            idx = int(event.key) - 1
            _, choice = self._options[idx]
            self.dismiss(PermissionResponse(
                tool_name=self._request.tool_name,
                choice=choice,
            ))
            event.stop()

    def _refresh_highlight(self) -> None:
        """更新高亮选项的 CSS class。"""
        for i in range(len(self._options)):
            opt = self.query_one(f"#perm-opt-{i}", Static)
            if i == self._selected:
                opt.set_classes("perm-option-highlighted")
            else:
                opt.set_classes("perm-option")


class CheeseballApp(App):
    """Cheeseball 主应用。

    布局: 对话历史（占满上方）+ 输入区域（固定在底部）

    快捷键:
    - Enter → 发送
    - Ctrl+J → 换行
    - Esc → 取消当前 Agent 运行
    - Ctrl+E → 退出
    - Ctrl+C → 复制选中文本（原生行为，不绑定）
    - Ctrl+V → 粘贴剪贴板
    - Ctrl+Y → 复制全部对话
    - Ctrl+Shift+→ / Ctrl+Shift+← → 切换权限模式
    """

    CSS = """
    ChatHistory {
        height: 1fr;
    }

    #perm_status {
        dock: bottom;
        height: 1;
        background: $primary 30%;
        color: $text;
        text-style: bold;
        padding: 0 2;
    }

    ChatInput {
        height: auto;
        max-height: 8;
        min-height: 3;
        dock: bottom;
        margin: 0 1;
    }

    """
    BINDINGS = [
        Binding("escape", "cancel", "取消", show=True),
        Binding("ctrl+e", "quit", "退出", show=True),
        Binding("ctrl+v", "paste", "粘贴", show=True),
        Binding("ctrl+y", "copy_all", "复制全部对话", show=True),
        Binding("ctrl+shift+right", "perm_next", "下一档权限", show=True, priority=True),
        Binding("ctrl+shift+left", "perm_prev", "上一档权限", show=True, priority=True),
    ]

    def __init__(
        self,
        agent: Agent,
        conversation: Conversation,
        registry=None,
        mcp_servers: dict | None = None,
        context_mgr=None,
        instructions: str = "",
        memories: str = "",
        memory_manager=None,
        session_archiver=None,
        cmd_registry: CommandRegistry | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._conversation = conversation
        self._is_streaming = False
        self._plan_mode = False
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._worker: object | None = None  # worker handle for potential future use
        self._perm_status: Static | None = None  # 权限模式状态栏
        self._tool_registry = registry
        self._mcp_servers: dict = mcp_servers or {}
        self._mcp_manager: object | None = None  # MCPClientManager | None
        self._context_mgr = context_mgr  # ContextManager | None (T16)
        self._current_tools: list = []  # 当前轮次的工具列表（T14 需要）
        # ch09
        self._instructions = instructions
        self._memories = memories
        self._memory_manager = memory_manager  # MemoryManager | None
        self._session_archiver = session_archiver  # SessionArchiver | None
        self._phase = AppPhase.IDLE  # ch09 F35
        self._last_interaction = 0.0  # 空闲计时（用于治理）
        # ch10: 命令系统
        self._cmd_registry = cmd_registry
        self._uictl: UICtlImpl | None = None
        self._autocomplete_menu: AutocompleteMenu | None = None

    def compose(self) -> ComposeResult:
        """构建 UI 组件树。"""
        self._chat_history = ChatHistory()
        self._chat_input = ChatInput()
        self._perm_status = Static("权限模式: default", id="perm_status")

        # ch10: 自动补全菜单
        if self._cmd_registry is not None:
            self._autocomplete_menu = AutocompleteMenu(self._cmd_registry)
            self._uictl = UICtlImpl(self)

        yield self._chat_history
        yield self._chat_input
        if self._autocomplete_menu is not None:
            yield self._autocomplete_menu
        yield self._perm_status

    async def on_mount(self) -> None:
        """挂载后禁用 kitty 键盘协议，然后触发 MCP 发现和指令/记忆注入。"""
        if sys.platform == "win32":
            # kitty 协议走 ReadFile (VT 流)，ReadConsoleInputW 不受其影响，
            # 因此 kitty 不能解决 IME VK=0 过滤器问题。
            # 禁用 kitty，通过 monkey-patch win32.py 的过滤器来修复。
            self._driver.write("\x1b[<u")

        # ch09: 注入指令和记忆到 SystemPromptBuilder
        if self._instructions or self._memories:
            combined = "\n\n".join(
                filter(None, [self._instructions, self._memories])
            )
            self._agent._builder.register(Module(
                id="custom-instructions",
                priority=80,
                content=combined,
                stable=True,
            ))

        # MCP 发现：连接所有配置的 server，注册工具
        if self._mcp_servers and self._tool_registry is not None:
            from cheeseball.mcp.manager import MCPClientManager

            self._mcp_manager = MCPClientManager()
            wrappers = await self._mcp_manager.connect_all(self._mcp_servers)
            for w in wrappers:
                self._tool_registry.register(w)

            # 汇总输出
            connected = len(getattr(self._mcp_manager, "_sessions", {}))
            total_servers = len(self._mcp_servers)
            total_tools = len(wrappers)
            print(
                f"[mcp] {connected}/{total_servers} servers connected, "
                f"{total_tools} tools registered",
                file=sys.stderr,
            )
        self._last_interaction = asyncio.get_event_loop().time()

        # ch10: 设置按键拦截器（自动补全菜单）
        if self._autocomplete_menu is not None:
            self._chat_input._key_interceptor = self._autocomplete_menu.handle_key

    def on_unmount(self) -> None:
        """退出时关闭所有 MCP 会话。"""
        if self._mcp_manager is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._mcp_manager.close_all())

    # ── 快捷键动作 ──────────────────────────────────────────────

    def action_cancel(self) -> None:
        """Esc: 取消当前 Agent 运行。"""
        if not self._is_streaming:
            return
        # 设置取消标志，Agent 在下一个检查点（通常 <20ms）发现并优雅退出，
        # 走完整的 ensure_assistant_tail → done 事件流程。
        self._agent.cancel()
        self._chat_history.show_info("已取消")

    def action_paste(self) -> None:
        """Ctrl+V: 从系统剪贴板粘贴到输入区域。"""
        text = _read_clipboard()
        if text:
            self._chat_input.insert(text)
            self._chat_input.focus()

    def action_copy_all(self) -> None:
        """Ctrl+Y: 复制全部对话内容到剪贴板。"""
        text = self._chat_history.get_all_text()
        if text:
            self.copy_to_clipboard(text)
            self._chat_history.show_info("已复制全部对话到剪贴板")
        else:
            self._chat_history.show_info("对话内容为空")

    def action_perm_next(self) -> None:
        """Tab: 切换到下一档权限模式。"""
        new_mode = self._agent.switch_permission_mode(+1)
        self._update_perm_status(new_mode)

    def action_perm_prev(self) -> None:
        """Shift+Tab: 切换到上一档权限模式。"""
        new_mode = self._agent.switch_permission_mode(-1)
        self._update_perm_status(new_mode)

    def _update_perm_status(self, mode) -> None:
        """更新状态栏显示当前权限模式。"""
        labels = {
            "default": "default（读放行/写询问/命令询问）",
            "acceptEdits": "acceptEdits（读写放行/命令询问）",
            "plan": "plan（只读，写+命令询问）",
            "bypassPermissions": "bypassPermissions（全放行，仅黑名单生效）",
        }
        label = labels.get(mode.value, mode.value)
        if self._perm_status is not None:
            self._perm_status.update(f"权限模式: {label}")
        self._chat_history.show_info(f"权限 → {label}")

    async def _show_permission_dialog(
        self, request: PermissionRequest
    ) -> PermissionResponse:
        """推送权限确认对话框并等待用户选择。

        Args:
            request: Agent 发来的权限请求。

        Returns:
            用户的选择（PermissionResponse）。
        """
        dialog = PermissionDialog(request)
        response = await self.push_screen_wait(dialog)
        return response

    # ── 事件处理 ──────────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """处理用户提交消息。"""
        if self._is_streaming:
            return
        self._process_user_input(event.text)

    def on_chat_input_text_changed(self, event: ChatInput.TextChanged) -> None:
        """文本变化 → 转发给自动补全菜单（T11）。"""
        if self._autocomplete_menu is not None:
            self._autocomplete_menu.on_text_changed(event.text)

    def on_autocomplete_menu_command_selected(
        self, event: AutocompleteMenu.CommandSelected
    ) -> None:
        """自动补全菜单选中命令 → 填入输入框（T11）。"""
        self._chat_input.clear()
        self._chat_input.insert(f"/{event.cmd_name} ")

    def _process_user_input(self, text: str) -> None:
        """处理用户输入，优先走命令路由（ch10），否则作为对话文本发送。"""
        self._last_interaction = asyncio.get_event_loop().time()

        # ── ch10: 命令解析与分流 ──
        if self._cmd_registry is not None and self._uictl is not None:
            parsed = Parser.parse(text)
            if parsed.cmd_name:
                # 斜杠命令 → 查找并分发
                cmd = self._cmd_registry.find(parsed.cmd_name)
                if cmd is not None:
                    cmd_dispatch(cmd, parsed.args, self._uictl)
                else:
                    self._chat_history.show_info(
                        f"未知命令: /{parsed.cmd_name}。输入 /help 查看可用命令"
                    )
                return

        # ── 普通文本 ──
        if self._phase == AppPhase.RESUMING:
            self._chat_history.show_info("请先完成或取消会话恢复")
            return

        self._chat_history.append_user_message(text)
        self._start_worker(text, plan_mode=self._plan_mode)

    def _start_worker(self, user_input: str, plan_mode: bool) -> None:
        """启动 Agent worker 并记录引用（用于 Esc 取消）。"""
        self._chat_input.disabled = True
        self._is_streaming = True
        self._worker = self.run_worker(
            self._run_agent(user_input, plan_mode=plan_mode),
            exclusive=False,
            thread=False,
            exit_on_error=False,
        )

    async def _cmd_resume(self) -> None:
        """执行 /resume 命令：扫描会话列表，弹出选择列表，恢复选中会话。"""
        try:
            from cheeseball.session.scanner import scan_sessions
            from cheeseball.session.recovery import load_jsonl

            sessions_root = Path.cwd() / ".cheeseball" / "sessions"
            sessions = scan_sessions(sessions_root)

            if not sessions:
                self._chat_history.show_info("没有可恢复的历史会话")
                self._phase = AppPhase.IDLE
                return

            # 暂存会话列表供 _handle_resume_selection 使用
            self._pending_resume_sessions = sessions

            # 用 Textual OptionList 展示会话列表
            from textual.widgets import OptionList
            from textual.widgets.option_list import Option

            options: list[Option] = []
            import time as _time
            now = _time.time()
            for s in sessions:
                # 相对时间
                delta = now - s.mtime
                if delta < 60:
                    rel_time = "刚刚"
                elif delta < 3600:
                    rel_time = f"{int(delta / 60)} 分钟前"
                elif delta < 86400:
                    rel_time = f"{int(delta / 3600)} 小时前"
                else:
                    rel_time = f"{int(delta / 86400)} 天前"

                size_kb = s.file_size / 1024
                if size_kb < 1024:
                    size_str = f"{size_kb:.1f} KB"
                else:
                    size_str = f"{size_kb / 1024:.1f} MB"

                prompt_line = f"{s.title}  |  {rel_time}  |  {s.model}  |  {size_str}"
                options.append(Option(prompt_line, id=s.session_id))

            option_list = OptionList(*options)
            self._chat_history.show_info("选择要恢复的会话 (Enter 确认, Esc 取消)")

            # 将 OptionList 挂载为临时组件（简化：直接操作）
            await self.mount(option_list)
            option_list.focus()

            # 等待用户选择
            selected_id: str | None = None
            try:
                # 简化的交互：监听按键
                while True:
                    key = await self._wait_for_key(("enter", "escape"))
                    if key == "escape":
                        break
                    elif key == "enter":
                        if option_list.highlighted is not None:
                            idx = option_list.highlighted
                            if 0 <= idx < len(sessions):
                                selected_id = sessions[idx].session_id
                        break
            finally:
                await option_list.remove()

            if selected_id is None:
                self._chat_history.show_info("已取消恢复")
                self._phase = AppPhase.IDLE
                return

            # 加载选中会话
            jsonl_path = sessions_root / selected_id / "conversation.jsonl"
            window_size = getattr(self._context_mgr, 'window', 200000) if self._context_mgr else 200000
            result = load_jsonl(jsonl_path, window_size)

            # 时间跨度提醒（> 4 小时）
            if result.time_gap_hours is not None and result.time_gap_hours > 4:
                hours = int(result.time_gap_hours)
                from cheeseball.provider import Message as PMsg
                result.messages.append(PMsg(
                    role="user",
                    content=f"<系统提示>距离上次对话已过约 {hours} 小时</系统提示>",
                ))

            # Token 超限 → 触发 compact
            if result.need_compact and self._context_mgr is not None:
                self._chat_history.show_info("上下文较大，正在压缩...")
                # 临时替换消息列表让 compact 操作
                old_messages = self._conversation._messages
                self._conversation._messages = result.messages
                try:
                    await self._context_mgr.compact(
                        self._conversation,
                        self._current_tools,
                        self._agent._builder.build_stable(),
                        self._agent._builder.build_environment(),
                        trigger="resume",
                    )
                    result.messages = self._conversation._messages
                except Exception:
                    pass
                finally:
                    self._conversation._messages = old_messages

            # 恢复消息历史
            self._conversation.rebuild_messages(result.messages)

            # 更新 archiver index
            if self._session_archiver is not None:
                max_idx = 0
                for msg in result.messages:
                    pass  # index 从 JSONL 读取
                # 设定为最后一条消息的 index + 1
                if result.messages:
                    # 从 JSONL 找到最大 index
                    import json
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
                                if obj.get("type") == "message":
                                    idx = obj.get("index", -1)
                                    if idx >= max_idx:
                                        max_idx = idx
                    except Exception:
                        pass
                self._session_archiver.index = max_idx + 1

            # 显示恢复的对话
            self._chat_history.clear()
            for msg in result.messages:
                if msg.role == "user":
                    if msg.tool_result:
                        self._chat_history.show_info(
                            f"[工具结果] {msg.tool_result.get('content', '')[:100]}"
                        )
                    elif msg.content:
                        self._chat_history.append_user_message(msg.content)
                elif msg.role == "assistant":
                    if msg.content:
                        self._chat_history.append_ai_message(msg.content)
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            self._chat_history.show_info(f"[工具调用] {tc.name}")

            self._chat_history.show_info(f"已恢复会话: {selected_id}")
            if result.warnings:
                for w in result.warnings:
                    self._chat_history.show_info(f"⚠ {w}")

            self._phase = AppPhase.IDLE

        except Exception as e:
            self._chat_history.show_error(f"恢复失败: {e}")
            self._phase = AppPhase.IDLE

    async def _wait_for_key(self, keys: tuple[str, ...]) -> str:
        """等待指定按键，返回按下的键名。"""
        import asyncio
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

        def on_key(event):
            if event.key in keys and not future.done():
                future.set_result(event.key)
                event.stop()

        self._driver._key_handlers.append(on_key)
        try:
            return await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError:
            return "escape"
        finally:
            try:
                self._driver._key_handlers.remove(on_key)
            except ValueError:
                pass

    def _handle_resume_selection(self, index_str: str) -> bool:
        """处理 /resume <序号> 会话选择。"""
        sessions = getattr(self, "_pending_resume_sessions", None)
        if sessions is None:
            self._chat_history.show_info("请先输入 /resume 查看会话列表")
            self._phase = AppPhase.IDLE
            return True
        try:
            idx = int(index_str) - 1
            if idx < 0 or idx >= len(sessions):
                self._chat_history.show_info(f"无效序号: {index_str}")
                self._phase = AppPhase.IDLE
                self._pending_resume_sessions = None
                return True
        except ValueError:
            self._chat_history.show_info("请输入 /resume <数字序号>")
            return True

        self._pending_resume_sessions = None
        selected = sessions[idx]

        async def _load():
            try:
                from cheeseball.session.recovery import load_jsonl

                sessions_root = Path.cwd() / ".cheeseball" / "sessions"
                jsonl_path = sessions_root / selected.session_id / "conversation.jsonl"
                window_size = getattr(self._context_mgr, 'window', 200000) if self._context_mgr else 200000
                result = load_jsonl(jsonl_path, window_size)

                if result.time_gap_hours is not None and result.time_gap_hours > 4:
                    hours = int(result.time_gap_hours)
                    from cheeseball.provider import Message as PMsg
                    result.messages.append(PMsg(
                        role="user",
                        content=f"<系统提示>距离上次对话已过约 {hours} 小时</系统提示>",
                    ))

                self._conversation.rebuild_messages(result.messages)

                if self._session_archiver is not None:
                    import json
                    max_idx = -1
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
                                if obj.get("type") == "message":
                                    idx = obj.get("index", -1)
                                    if idx > max_idx:
                                        max_idx = idx
                    except Exception:
                        pass
                    self._session_archiver.index = max_idx + 1

                self._chat_history.clear()
                for msg in result.messages:
                    if msg.role == "user":
                        if msg.tool_result:
                            self._chat_history.show_info(
                                f"[工具结果] {msg.tool_result.get('content', '')[:100]}"
                            )
                        elif msg.content:
                            self._chat_history.append_user_message(msg.content)
                    elif msg.role == "assistant":
                        if msg.content:
                            self._chat_history.append_ai_message(msg.content)
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                self._chat_history.show_info(f"[工具调用] {tc.name}")

                self._chat_history.show_info(f"已恢复会话: {selected.session_id}")
                for w in result.warnings:
                    self._chat_history.show_info(f"⚠ {w}")

            except Exception as e:
                self._chat_history.show_error(f"恢复失败: {e}")
            finally:
                self._phase = AppPhase.IDLE

        self.run_worker(_load(), exclusive=False, thread=False, exit_on_error=False)
        return True

    async def _run_agent(
        self, user_input: str, plan_mode: bool = False
    ) -> None:
        """在 worker 中运行 Agent，消费 AgentEvent 流并更新 UI。"""
        self._phase = AppPhase.RUNNING
        natural_stop = False
        try:
            full_text = ""

            # 更新当前工具列表（供 commands.py /compact 使用）
            if self._tool_registry is not None:
                self._current_tools = self._tool_registry.export_definitions(
                    readonly_only=plan_mode
                )

            async for ev in self._agent.run(
                self._conversation, user_input, plan_mode=plan_mode
            ):
                # ── 文本增量 ──
                if ev.text:
                    self._chat_history.append_ai_chunk(ev.text)
                    full_text += ev.text

                # ── 工具开始 ──
                if ev.tool_start is not None:
                    self._chat_history.show_tool_start(ev.tool_start)

                # ── 工具结束 ──
                if ev.tool_end is not None:
                    self._chat_history.show_tool_end(ev.tool_end)
                    if full_text:
                        self._chat_history.finish_ai_message(full_text)
                        full_text = ""

                # ── Token 用量 ──
                if ev.token_usage is not None:
                    self._total_input_tokens += ev.token_usage.input_tokens
                    self._total_output_tokens += ev.token_usage.output_tokens

                # ── 迭代进度 ──
                if ev.iteration is not None:
                    self._chat_history.show_progress(
                        ev.iteration.current, ev.iteration.max
                    )

                # ── 权限确认请求 ──
                if ev.permission_request is not None:
                    response = await self._show_permission_dialog(
                        ev.permission_request
                    )
                    self._agent._perm_queue.put_nowait(response)

                # ── 错误 ──
                if ev.error:
                    self._chat_history.show_error(ev.error)

                # ── 循环结束 ──
                if ev.done is not None:
                    if full_text:
                        self._chat_history.finish_ai_message(full_text)
                    if self._plan_mode and ev.done.reason == StopReason.NATURAL:
                        self._chat_history.show_info(
                            "计划已完成。输入 /do 执行，或输入新任务。"
                        )
                    if ev.done.reason == StopReason.NATURAL:
                        natural_stop = True
                    break

            # ch09: 自然停下后触发记忆更新（F25-F27）
            if natural_stop and self._memory_manager is not None:
                provider = self._agent._provider
                from cheeseball.memory.updater import MemoryUpdater
                updater = MemoryUpdater(self._memory_manager, provider)
                snapshot = list(self._conversation._messages)
                asyncio.create_task(updater.update(snapshot))

        except asyncio.CancelledError:
            # Worker 被 Esc 取消 — agent 本身已处理 ensure_assistant_tail
            pass

        except Exception as e:
            self._chat_history.show_error(str(e))

        finally:
            self._phase = AppPhase.IDLE
            self._chat_input.disabled = False
            self._is_streaming = False
            self._chat_input.focus()
            self._worker = None


# ── 剪贴板工具 ──────────────────────────────────────────────────


def _read_clipboard() -> str:
    """读取系统剪贴板文本内容。"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return result.stdout
    except Exception:
        pass
    return ""
