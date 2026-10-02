"""UI 层：对话渲染区域，每个消息块一个 Static widget，动态布局 + 智能滚动 + 工具行。

每个消息块是独立的 Static，按需 mount 到 VerticalScroll。
滚动仅当用户在底部时自动追底。
"""

from __future__ import annotations

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from cheeseball.agent.events import ToolStart, ToolEnd

# 颜色定义
COLOR_USER = "white"
COLOR_AI = "#FF9500"
COLOR_THINKING = "#6B7280"
COLOR_ERROR = "#EF4444"
COLOR_WELCOME = "cyan"
COLOR_TOOL = "#3B82F6"
COLOR_TOOL_SUCCESS = "#22C55E"
COLOR_TOOL_ERROR = "#EF4444"
COLOR_INFO = "#6B7280"
COLOR_PROGRESS = "#9CA3AF"


class ChatHistory(Widget):
    """对话历史渲染区域。

    每个消息块（用户/AI/工具行/错误/进度）对应一个 Static 子 widget，
    挂载在 VerticalScroll 内部。Textual 原生排版，无 Group 兼容问题。
    流式期间只更新最后一个 widget；自动滚动仅在用户在底部时触发。
    """

    def __init__(self) -> None:
        super().__init__()
        # (type, content, is_streaming)
        self._blocks: list[tuple[str, str, bool]] = []
        self._widgets: list[Static] = []
        self._streaming: bool = False
        self._streaming_text: str = ""
        # 当前轮进行中的工具行: [(tool_id, tool_name, args_preview)]
        self._active_tools: list[tuple[str, str, str]] = []

    def compose(self):
        with VerticalScroll() as self._scroll:
            pass  # child widgets 动态 mount
        yield self._scroll

    def on_mount(self) -> None:
        self._show_welcome()

    # ── 公开接口 ──────────────────────────────────────────────

    def append_user_message(self, content: str) -> None:
        self._blocks.append(("user", content, False))
        self._sync_widgets()

    def append_ai_chunk(self, text: str) -> None:
        self._streaming_text += text
        if self._streaming:
            self._blocks[-1] = ("ai", self._streaming_text, True)
        else:
            self._blocks.append(("ai", self._streaming_text, True))
            self._streaming = True
        self._sync_widgets()

    def finish_ai_message(self, full_text: str) -> None:
        if self._streaming and self._blocks:
            self._blocks[-1] = ("ai", full_text, False)
            self._streaming = False
            self._streaming_text = ""
            self._sync_widgets()

    def show_tool_start(self, ev: ToolStart) -> None:
        """工具调用开始：在动态区新增工具行。"""
        self._active_tools.append((ev.tool_id, ev.tool_name, ev.args_preview))
        # 渲染所有进行中的工具行
        self._render_active_tools()

    def show_tool_end(self, ev: ToolEnd) -> None:
        """工具调用结束：FIFO 弹出队首，将结果写入历史。"""
        if self._active_tools:
            popped = self._active_tools.pop(0)
            _, tool_name, _ = popped
        else:
            tool_name = ev.tool_name

        icon = "✖" if ev.is_error else "✓"
        t = "tool_error" if ev.is_error else "tool_success"
        summary = ev.result_summary or "(无输出)"
        self._blocks.append((t, f"{icon} {tool_name}: {summary}", False))

        # 刷新：清除旧的工具行 blocks，重新渲染剩余活跃工具
        self._refresh_tool_blocks()

    def show_progress(self, current: int, max_val: int) -> None:
        """显示迭代轮次。"""
        self._blocks.append(("progress", f"🔄 轮次 {current}/{max_val}", False))
        self._sync_widgets()

    def show_error(self, message: str) -> None:
        self._blocks.append(("error", f"❌ {message}", False))
        self._sync_widgets()

    def show_info(self, message: str) -> None:
        self._blocks.append(("info", f"ℹ {message}", False))
        self._sync_widgets()

    def append_ai_message(self, content: str) -> None:
        """追加一条完整的 AI 消息（非流式，直接 Markdown 渲染）。"""
        self._blocks.append(("ai", content, False))
        self._sync_widgets()

    def clear(self) -> None:
        """清空所有对话历史和渲染 widget。"""
        self._blocks.clear()
        for w in self._widgets:
            w.remove()
        self._widgets.clear()
        self._streaming = False
        self._streaming_text = ""
        self._active_tools.clear()

    def get_all_text(self) -> str:
        lines: list[str] = []
        for t, c, _ in self._blocks:
            if t == "user":
                lines.append(f"You: {c}")
            elif t == "ai":
                lines.append(f"AI: {c}")
            elif t in (
                "tool_start", "tool_success", "tool_error",
                "error", "info", "progress",
            ):
                lines.append(c)
        return "\n\n".join(lines)

    # ── 内部方法 ──────────────────────────────────────────────

    def _show_welcome(self) -> None:
        welcome = Static(Text(
            "\n  🐱 Cheeseball — Enter 发送 | Esc 取消 | Ctrl+V 粘贴 | Ctrl+Y 复制全部 | Ctrl+C 退出\n",
            style=f"bold italic {COLOR_WELCOME}",
        ))
        self._scroll.mount(welcome)

    def _is_at_bottom(self) -> bool:
        try:
            return (
                self._scroll.scroll_offset.y
                >= self._scroll.max_scroll_offset.y - 2
            )
        except Exception:
            return True

    def _render_active_tools(self) -> None:
        """为每个活跃工具生成 tool_start block。"""
        # 先清除旧的 tool_start blocks
        self._blocks = [(t, c, s) for t, c, s in self._blocks if t != "tool_start"]
        # 重新生成
        for _tid, name, args_preview in self._active_tools:
            label = f"● {name}({args_preview})" if args_preview else f"● {name}"
            self._blocks.append(("tool_start", f"{label} ... Running", False))
        self._sync_widgets()

    def _refresh_tool_blocks(self) -> None:
        """清除旧 tool_start，重新渲染活跃工具（show_tool_end 后调用）。"""
        self._blocks = [(t, c, s) for t, c, s in self._blocks if t != "tool_start"]
        for _tid, name, args_preview in self._active_tools:
            label = f"● {name}({args_preview})" if args_preview else f"● {name}"
            self._blocks.append(("tool_start", f"{label} ... Running", False))
        self._sync_widgets()

    def _sync_widgets(self) -> None:
        """将 _blocks 同步到子 widget：新建不足的 widget，更新已有的内容。"""
        was_at_bottom = self._is_at_bottom()

        # 新建不足的 widget
        while len(self._widgets) < len(self._blocks):
            w = Static("")
            self._scroll.mount(w)
            self._widgets.append(w)

        # 更新所有 widget 的渲染内容
        for i, (t, content, is_streaming) in enumerate(self._blocks):
            self._widgets[i].update(self._render_block(t, content, is_streaming))

        if was_at_bottom:
            self._scroll.scroll_end(animate=False)

    def _render_block(self, t: str, content: str, is_streaming: bool):
        """单个消息块 → Rich renderable。"""
        if t == "user":
            return Text.assemble(
                Text("\n", style=COLOR_USER),
                Text("🧑 你", style=f"bold {COLOR_USER}"),
                Text(f"\n{content}", style=COLOR_USER),
            )

        if t == "ai":
            header = Text.assemble(
                Text("\n"),
                Text("🤖 AI", style=f"bold {COLOR_AI}"),
            )
            if is_streaming:
                return Text.assemble(header, Text(f"\n{content}", style=COLOR_AI))
            else:
                try:
                    return Group(
                        header,
                        Markdown(content, code_theme="monokai"),
                    )
                except Exception:
                    return Text.assemble(header, Text(f"\n{content}", style=COLOR_AI))

        if t == "tool_start":
            return Text(content, style=f"bold {COLOR_TOOL}")

        if t == "tool_success":
            return Text(content, style=f"bold {COLOR_TOOL_SUCCESS}")

        if t == "tool_error":
            return Text(content, style=f"bold {COLOR_TOOL_ERROR}")

        if t == "error":
            return Text(content, style=f"bold {COLOR_ERROR}")

        if t == "info":
            return Text(content, style=f"dim {COLOR_INFO}")

        if t == "progress":
            return Text(content, style=f"dim {COLOR_PROGRESS}")

        return Text(content)
