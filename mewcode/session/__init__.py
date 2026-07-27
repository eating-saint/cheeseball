"""会话模块：session ID 生成、JSONL 存档、扫描与恢复（ch09）."""

from __future__ import annotations

import secrets
from datetime import datetime


def new_session_id() -> str:
    """返回 YYYYMMDD-HHMMSS-xxxx 格式的 session ID。

    xxxx 为 4 字符随机十六进制后缀，防同秒碰撞。
    """
    now = datetime.now()
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
