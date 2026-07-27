"""<system-reminder> 补充消息构造。

提供 build_reminder() 函数，根据当前模式和迭代轮次生成适时的
系统提醒文本，通过消息通道注入而不污染持久历史。
"""

from __future__ import annotations


def build_reminder(mode: str, iteration: int) -> str:
    """根据模式和迭代轮次构造 <system-reminder> 文本。

    Args:
        mode: "normal" 或 "plan"。
        iteration: 当前迭代轮次（从 1 开始）。

    Returns:
        <system-reminder> 包裹的提醒文本，normal 模式返回空字符串。
    """
    if mode == "normal":
        return ""

    # Plan Mode：首轮 + 每 3 轮完整提醒
    if mode == "plan":
        if iteration == 1 or iteration % 3 == 1:
            content = (
                "你处于规划模式，只能使用只读工具。"
                "请分析问题并输出执行计划，不要执行任何写操作。"
            )
        else:
            content = "（仍在规划模式——只读工具可用）"

        return f"<system-reminder>\n{content}\n</system-reminder>"

    return ""
