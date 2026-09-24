"""context_window 解析 + 协议默认值 + 阈值计算（F30-F33）。"""

from cheeseball.config.loader import ProviderConfig
from cheeseball.context.constants import (
    AUTO_SAFETY_MARGIN,
    MANUAL_SAFETY_MARGIN,
    SUMMARY_OUTPUT_RESERVE,
)

# F31: 各协议的默认 context_window
DEFAULT_WINDOWS: dict[str, int] = {
    "anthropic": 200_000,
    "openai": 128_000,
}


def resolve_context_window(config: ProviderConfig) -> int:
    """解析最终的 context_window。

    F30: config.context_window > 0 则用它。
    F31: 否则按 config.protocol 取协议默认值。
    F32: 未识别的 protocol 回退 200000。

    Args:
        config: 已加载的 ProviderConfig。

    Returns:
        最终使用的 context_window token 数。
    """
    if config.context_window > 0:
        return config.context_window
    protocol = config.protocol.lower()
    return DEFAULT_WINDOWS.get(protocol, 200_000)


def auto_trigger_threshold(window: int) -> int:
    """自动触发摘要的 token 阈值（F7）。

    context_window - 摘要输出预留(20K) - 自动安全边距(13K)。
    例如: 200000 → 167000。

    Args:
        window: context_window 值。

    Returns:
        自动触发阈值。
    """
    return window - SUMMARY_OUTPUT_RESERVE - AUTO_SAFETY_MARGIN


def manual_precheck_threshold(window: int) -> int:
    """手动 /compact 预检查的 token 阈值（F23）。

    context_window - 摘要输出预留(20K) - 手动安全边距(3K)。
    例如: 200000 → 177000。
    比自动阈值更激进（只留 3K 边距）。

    Args:
        window: context_window 值。

    Returns:
        手动预检查阈值。
    """
    return window - SUMMARY_OUTPUT_RESERVE - MANUAL_SAFETY_MARGIN
