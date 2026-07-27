"""Token 估算器：锚定真实 usage + 增量字符数/3.5（F13-F14）。

不引入精确 tokenizer，用字符数除以经验常量估算增量 token。
该类不保证线程安全——由调用方（ContextManager）保证串行使用。
"""

from __future__ import annotations

from dataclasses import dataclass

from mewcode.context.constants import ESTIMATE_CHARS_PER_TOKEN
from mewcode.provider import Usage


@dataclass
class TokenEstimate:
    """token 估算快照。

    Attributes:
        total: 估算总 token = anchor + incremental
        anchor: 最后真实 usage 锚点值
        incremental: 锚点后的增量（chars_since / chars_per_token）
        chars_per_token: 使用的字符/token 比率
    """

    total: int
    anchor: int
    incremental: int
    chars_per_token: float


class TokenEstimator:
    """轻量 token 估算器。

    用法::

        est = TokenEstimator()
        est.update_anchor(Usage(input_tokens=100, output_tokens=50, ...))
        est.add_chars(350)
        print(est.estimate().total)  # ~260
        est.reset_anchor()
    """

    def __init__(self) -> None:
        self._anchor: int = 0
        self._chars_since: int = 0

    def update_anchor(self, usage: Usage) -> None:
        """用真实 usage 替换锚点，清零增量字符计数。

        每次 API 请求结束后调用，确保锚点同步到最新的真实统计。
        usage.total = input + output + cache_write + cache_read。

        Args:
            usage: 从 provider 返回的真实 token 用量。
        """
        self._anchor = (
            usage.input_tokens
            + usage.output_tokens
            + usage.cache_write_tokens
            + usage.cache_read_tokens
        )
        self._chars_since = 0

    def add_chars(self, count: int) -> None:
        """累加锚点后的字符数（用于增量估算）。

        Args:
            count: 本次新增的字符数。
        """
        self._chars_since += count

    def estimate(self) -> TokenEstimate:
        """返回当前 token 估算快照。

        Returns:
            TokenEstimate: total = anchor + int(chars_since / 3.5)。
        """
        incremental = int(self._chars_since / ESTIMATE_CHARS_PER_TOKEN)
        return TokenEstimate(
            total=self._anchor + incremental,
            anchor=self._anchor,
            incremental=incremental,
            chars_per_token=ESTIMATE_CHARS_PER_TOKEN,
        )

    def reset_anchor(self) -> None:
        """重置锚点为零（紧急压缩或 compact 后使用，F14/F25）。"""
        self._anchor = 0
        self._chars_since = 0
