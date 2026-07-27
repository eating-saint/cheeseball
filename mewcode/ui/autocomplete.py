"""自动补全菜单（F18-F29, T9）。

Textual widget，监听 ChatInput.Changed 消息，
在输入以 / 开头时弹出候选命令列表。
"""

from __future__ import annotations

from textual.widgets import Static
from textual.message import Message
from rich.text import Text

from mewcode.cmd.registry import CommandRegistry

# 颜色
COLOR_MENU_BG = "#1E1E2E"
COLOR_MENU_BORDER = "#3B82F6"
COLOR_HIGHLIGHT = "#3B82F6"
COLOR_DIM = "#6B7280"
MENU_MAX_HEIGHT = 8


class AutocompleteMenu(Static):
    """斜杠命令自动补全菜单。

    继承 Static（而非 Widget），利用 Static 自带的 render() 提供合法的
    Rich renderable，避免 Widget.visual 为 None 导致 Textual 渲染器崩溃。

    非 Modal overlay，不抢焦点。紧贴输入框下方，状态栏上方。
    """

    class CommandSelected(Message):
        """用户选中了某条命令。"""

        def __init__(self, cmd_name: str) -> None:
            super().__init__()
            self.cmd_name = cmd_name

    def __init__(self, registry: CommandRegistry) -> None:
        super().__init__("")
        self._registry = registry
        self._visible = False
        self._highlight_index = 0
        self._candidates: list[str] = []  # 当前候选命令名列表

    def on_mount(self) -> None:
        """挂载后默认隐藏：display: none 使 Textual 完全跳过布局。"""
        self.styles.display = "none"

    # ── 公开接口 ──

    def on_text_changed(self, text: str) -> None:
        """由外部调用（app.py 监听 ChatInput.TextChanged 后转发）。"""
        # F27: 含换行符不激活
        if "\n" in text:
            if self._visible:
                self._hide()
            return

        # F18: 首字符 / 激活
        if text.startswith("/"):
            prefix = text[1:]  # 去掉 /
            self._update_candidates(prefix)
        else:
            # F20: 不再以 / 开头 → 关闭
            if self._visible:
                self._hide()

    def handle_key(self, key: str) -> bool:
        """处理补全菜单中的按键。返回 True 表示已消费。

        Args:
            key: 按键名（"up", "down", "enter", "tab", "escape"）。

        Returns:
            True 如果按键被菜单消费且不应再传递给输入框。
        """
        if not self._visible:
            return False

        if key == "escape":
            # F25: ESC 关闭菜单，输入框保持
            self._hide()
            return True

        if key == "up":
            # F23: 上键切换高亮
            if self._candidates:
                self._highlight_index = (
                    self._highlight_index - 1
                ) % len(self._candidates)
                self._refresh_menu()
            return True

        if key == "down":
            # F23: 下键切换高亮
            if self._candidates:
                self._highlight_index = (
                    self._highlight_index + 1
                ) % len(self._candidates)
                self._refresh_menu()
            return True

        if key in ("enter", "tab"):
            # F24: Enter/Tab 选中执行
            if self._candidates and 0 <= self._highlight_index < len(self._candidates):
                cmd_name = self._candidates[self._highlight_index]
                self._hide()
                self.post_message(self.CommandSelected(cmd_name))
            return True

        return False

    def is_visible(self) -> bool:
        """外部查询菜单是否可见。"""
        return self._visible

    # ── 内部方法 ──

    def _update_candidates(self, prefix: str) -> None:
        """从 registry 获取前缀匹配的候选并刷新渲染。"""
        cmds = self._registry.search_prefix(prefix)
        self._candidates = [c.name for c in cmds]
        self._highlight_index = 0

        if self._candidates:
            if not self._visible:
                self._show()
            self._refresh_menu()
        elif self._visible:
            # F28: 零匹配 → 显示「无匹配」
            self._refresh_menu_empty()

    def _show(self) -> None:
        """显示菜单：用 display: block 让 Textual 正常参与布局。"""
        self._visible = True
        self.styles.display = "block"

    def _hide(self) -> None:
        """隐藏菜单：display: none 让 Textual 完全跳过布局。"""
        self._visible = False
        self.styles.display = "none"

    def _refresh_menu(self) -> None:
        """重建候选列表内容并写入 Static.update()。

        注意：不能命名为 _render —— Textual Widget 内部同名方法用于
        获取 Rich renderable，覆盖会导致布局计算时 visual 为 None 崩溃。
        """
        cmds = self._registry.search_prefix(
            self._candidates[0][:1] if self._candidates else ""
        )
        # 重建完整 CommandDef 列表以获取描述
        visible = self._registry.list_visible()
        desc_map = {c.name: c.description for c in visible}

        max_name_len = max((len(n) for n in self._candidates), default=0)
        lines: list[Text] = []

        for i, name in enumerate(self._candidates):
            desc = desc_map.get(name, "")
            prefix = "▸ " if i == self._highlight_index else "  "
            line = Text(prefix, style=COLOR_HIGHLIGHT if i == self._highlight_index else "")
            line.append(f"/{name:<{max_name_len}}", style=f"bold {COLOR_HIGHLIGHT}" if i == self._highlight_index else "")
            if desc:
                line.append(f"  {desc}", style=f"dim {COLOR_DIM}")
            lines.append(line)

        # N5: 高度上限，超出可滚动（简化：限制候选数）
        if len(lines) > MENU_MAX_HEIGHT:
            lines = lines[:MENU_MAX_HEIGHT]

        content = Text("\n").join(lines) if lines else Text("")
        content.append("\n")
        content.append(Text("─" * 40, style=f"dim {COLOR_DIM}"))

        self.update(content)

    def _refresh_menu_empty(self) -> None:
        """零匹配提示（F28）。"""
        content = Text("无匹配", style=f"dim {COLOR_DIM}")
        self.update(content)
