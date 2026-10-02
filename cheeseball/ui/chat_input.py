"""UI 层：多行输入组件，支持历史浏览和快捷键."""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class ChatInput(TextArea):
    """多行文本输入区域。

    快捷键:
    - Enter — 提交当前输入
    - Ctrl+J — 输入中换行
    - Up/Down — 浏览历史输入（最近 100 条）

    注意:
    - 中文输入法下 Shift 被 IME 消费，Shift+Enter / Shift+符号键不可用
    - Ctrl+J 换行在所有终端上都可用（推荐方案）
    """

    class Submitted(Message):
        """输入提交事件，携带文本内容."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class TextChanged(Message):
        """输入文本变化事件，供自动补全菜单监听（F18, T8）."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__()
        # 历史记录（最多保留 100 条）
        self._history: list[str] = []
        self._history_index: int = -1  # -1 表示当前正在新编辑
        self._key_interceptor: object | None = None  # 按键拦截回调: (key: str) -> bool

    def on_mount(self) -> None:
        """组件挂载后设置占位文本。"""
        self.placeholder = "输入消息，Enter 发送，Ctrl+J 换行"

    def _on_key(self, event: events.Key) -> None:
        """拦截按键事件。

        只处理纯 Enter（提交）和历史导航。
        Shift+Enter 和 Ctrl+J 留给 TextArea 原生处理（插入换行）。
        """
        # ── 按键拦截器（自动补全菜单） ──
        if self._key_interceptor is not None:
            interceptor = self._key_interceptor
            if interceptor(event.key):  # type: ignore[call-arg]
                event.prevent_default()
                return

        # ── 纯 Enter → 提交 ──
        if event.key == "enter":
            # 安全检测修饰键（依赖 kitty 协议，不支持时回退到 False）
            shift = getattr(event, "shift", False)
            ctrl = getattr(event, "ctrl", False)
            alt = getattr(event, "alt", False)
            if shift or ctrl or alt:
                # 有修饰键 → 交给 TextArea 处理（插入换行等默认行为）
                return
            # 纯 Enter → 提交
            self.action_submit()
            event.prevent_default()
            return

        # ── Up/Down → 浏览历史 ──
        if event.key == "up":
            self._navigate_history(-1)
            event.prevent_default()
            self._post_changed()
            return
        if event.key == "down":
            self._navigate_history(1)
            event.prevent_default()
            self._post_changed()
            return

        # ── 每次按键后通知补全菜单 ──
        # FIX[1.1]: 使用 call_after_refresh 延迟到 TextArea 插入字符后再读取 self.text
        # 同步调用时 _on_key 在字符插入前触发，self.text 还是按键前的内容
        self.call_after_refresh(self._post_changed)

    def _on_paste(self, event: events.Paste) -> None:
        """粘贴事件也发送 Changed 消息。"""
        # 等 TextArea 默认处理后再发送
        self.call_after_refresh(self._post_changed)

    def _post_changed(self) -> None:
        """发送 TextChanged 消息（T8）。"""
        self.post_message(self.TextChanged(self.text))

    def action_submit(self) -> None:
        """提交当前输入文本。"""
        text = self.text.strip()
        if not text:
            return

        # 加入历史
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            # 限制历史数量
            if len(self._history) > 100:
                self._history.pop(0)
        self._history_index = -1

        # 发送消息
        self.post_message(self.Submitted(text))
        self.clear()

    def _navigate_history(self, direction: int) -> None:
        """浏览历史输入。

        Args:
            direction: -1 向上（更早），1 向下（更新）
        """
        if not self._history:
            return

        new_index = self._history_index + direction

        if new_index < -1:
            return  # 已经是最新
        if new_index >= len(self._history):
            return  # 已经是最旧

        self._history_index = new_index

        if new_index == -1:
            # 回到当前编辑（清空）
            self.clear()
        else:
            # 显示历史条目
            self.clear()
            self.insert(self._history[len(self._history) - 1 - new_index])
