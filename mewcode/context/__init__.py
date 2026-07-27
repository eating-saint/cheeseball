"""上下文管理包（ch08）。

提供两层压缩机制：
- 第 1 层：工具结果预防性落盘（offloader + ledger）
- 第 2 层：LLM 摘要压缩（summarizer + estimator + recovery）

对 Agent 主循环仅暴露 ContextManager 门面。
"""

from mewcode.context.manager import ContextManager

__all__ = ["ContextManager"]
