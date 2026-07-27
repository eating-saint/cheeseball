"""prompt 包：结构化系统提示与缓存策略。

提供模块化的系统提示装配，将系统提示从单段字符串升级为
「模块化组装 + 缓存分层 + 动态注入」的结构化系统。
"""

from __future__ import annotations

from mewcode.prompt.builder import SystemPromptBuilder
from mewcode.prompt.modules import Module
from mewcode.prompt.reminder import build_reminder

__all__ = ["Module", "SystemPromptBuilder", "build_reminder"]
